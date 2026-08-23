"""MCP 兜底两层（doc 17：例程重试耗尽后切兜底）。

- AdaptiveFallback：无 LLM。重新读树 + 关键词启发式决定动作（读取类返回
  树、点击类匹配 label 点击、输入类匹配文本框填充）。无法确定动作返回
  None，交由上层升级 LLM。写操作（发送/回车）不在此自动执行——那是
  预写例程 + 审批流的职责。
- LLMFallback：注入 FallbackLLM（复用 planner 同款 with_structured_output
  模式），ReAct ≤ max_steps 步：读树摘要 -> LLM 决策 {tool,args,done}
  -> 调工具 -> 观察。

配置：browser_mcp_fallback_mode = adaptive | llm | both | off（默认 both）。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.agent.graph.deps import LLMPlanError
from app.agent.prompts.planner import PlannerLLMConfig, StructuredChatModel
from app.agent.tools.routine import (
    TargetSpec,
    decode_tree_text,
    match_candidates,
    parse_tree,
    truncate_tree,
)
from app.agent.tools.runner import AdapterToolResult, ToolCaller, extract_tree_text
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SessionFactoryLike(Protocol):
    """异步会话工厂（async_sessionmaker 鸭子类型，供装配函数注入）。"""

    def __call__(self) -> Any: ...  # noqa: ANN401 - 返回 AsyncSession 上下文管理器

# 允许兜底调用的工具（全部经 adapter 白名单/风险/URL 校验）
_FALLBACK_TOOLS = frozenset(
    {
        "get_windows_and_tabs",
        "chrome_switch_tab",
        "chrome_navigate",
        "chrome_read_page",
        "chrome_get_web_content",
        "chrome_click_element",
        "chrome_fill_or_select",
        "chrome_keyboard",
        "chrome_handle_dialog",
        "chrome_screenshot",
    }
)

# 动作意图关键词（goal 匹配；中文 + 英文）
_READ_WORDS = ("读取", "提取", "获取", "查看", "浏览", "分析", "read", "get", "extract", "view")
_CLICK_WORDS = ("点击", "打开", "进入", "click", "open", "tap", "press")
_FILL_WORDS = ("输入", "填写", "填入", "搜索", "查找", "type", "fill", "search")
# 写操作关键词：命中即不自动执行（需预写例程 + 审批流），返回 None 升级
_SEND_WORDS = ("发送", "提交", "回车", "send", "submit", "enter")

# LLM 兜底读树摘要上限（token 预算）
_FALLBACK_TREE_MAX_CHARS = 6000


class FallbackDecision(BaseModel):
    """LLM 兜底单步决策（with_structured_output 解析目标）。"""

    tool: str = Field(description="要调用的 chrome_* 工具名（安全白名单内）")
    args: dict[str, Any] = Field(default_factory=dict, description="工具参数")
    done: bool = Field(False, description="目标是否已完成，完成则终止循环")
    note: str | None = Field(None, description="简要理由（审计用）")


class FallbackLLM(Protocol):
    """LLM 兜底的决策接口（生产 LangchainFallbackLLM，测试 Fake）。"""

    async def decide(
        self,
        *,
        page_summary: str,
        goal: str,
        last_error: str | None,
    ) -> FallbackDecision: ...


class FallbackLLMError(Exception):
    """LLM 兜底调用失败（网络/超时/输出非法），由调用方分类转错误态。"""


_FALLBACK_SYSTEM_PROMPT = """你是求职自动化 Agent 的浏览器操作员。目标无法用预写例程
完成，你需要读取页面 a11y 树后决定下一步工具调用。

可用工具（只能从中选择，全部经过安全白名单）：
- chrome_read_page: 读取当前页面 a11y 树（无参数，每次决策先调它）
- chrome_click_element: 点击元素，参数 ref 或 selector
- chrome_fill_or_select: 输入文本，参数 ref/selector + value
- chrome_keyboard: 按键，参数 key（Enter/Escape/Tab/ArrowDown...）
- chrome_navigate: 页内跳转，参数 url（仅限 zhipin.com 白名单域名）
- chrome_handle_dialog: 处理弹窗，参数 accept
- chrome_get_web_content: 读取页面正文文本
- chrome_screenshot: 截图
- chrome_switch_tab / get_windows_and_tabs: 标签页管理

授权状态（2026-08-23）：chrome_javascript 已放行（Boss 技能主路径），仅
chrome_network_request 仍为高危待授权。兜底仍优先 chrome_read_page 等只读树动作；
写操作发送/投递仍须 Skill 级授权/审批，不自动执行。

决策纪律：
1. 每次决策先调 chrome_read_page 获取最新树，再决定动作
2. 元素通过 a11y 树中的 ref_* 引用（如 {"ref": "ref_1"}）
3. 涉及发送/提交等写操作且未确认授权时，输出 done=false 并说明原因
4. done=true 仅在目标确认完成后输出
"""

_FALLBACK_USER_TEMPLATE = """【目标】{goal}
【当前页面 a11y 树】
{page_summary}
【上一步结果/错误】{last_error}

请决策下一步。"""


class LangchainFallbackLLM:
    """FallbackLLM 实现：LangChain 结构化输出 -> FallbackDecision。"""

    def __init__(self, config: PlannerLLMConfig, model: StructuredChatModel | None = None) -> None:
        self._config = config
        if model is None:
            # 局部导入：仅生产路径依赖 langchain-openai，测试注入 Fake 免依赖
            from langchain_openai import ChatOpenAI
            from pydantic import SecretStr

            model = ChatOpenAI(
                model=config.model,
                api_key=SecretStr(config.api_key),
                base_url=config.base_url,
                temperature=config.temperature,
                timeout=config.timeout,
                max_retries=0,  # 重试交给调用方，避免双层重试
            )
        self._structured = model.with_structured_output(FallbackDecision)

    async def decide(
        self,
        *,
        page_summary: str,
        goal: str,
        last_error: str | None,
    ) -> FallbackDecision:
        """LLM 决策；失败统一抛 FallbackLLMError（调用方分类处理）。"""
        prompt = _FALLBACK_USER_TEMPLATE.format(
            goal=goal,
            page_summary=page_summary,
            last_error=last_error or "（无）",
        )
        try:
            dto = await self._structured.ainvoke(
                [("system", _FALLBACK_SYSTEM_PROMPT), ("human", prompt)]
            )
        except LLMPlanError:
            raise
        except Exception as exc:
            logger.warning("fallback llm call failed", extra={"error": str(exc), "model": self._config.model})
            raise FallbackLLMError(str(exc)) from exc
        if not isinstance(dto, FallbackDecision):
            msg = f"unexpected structured output type: {type(dto).__name__}"
            raise FallbackLLMError(msg)
        return dto


async def create_fallback_llm_from_settings(
    session_factory: SessionFactoryLike,
    user_id: int,
) -> LangchainFallbackLLM | None:
    """从用户 Settings.llm 组装兜底 LLM；未配置时返回 None（调用方降级）。"""
    from app.service.setting import SettingsService

    async with session_factory() as session:
        current = await SettingsService(session).get_llm_runtime_config(user_id)

    api_key = current.get("api_key")
    model = current.get("model")
    if not api_key or not model:
        return None
    return LangchainFallbackLLM(
        PlannerLLMConfig(
            model=str(model),
            api_key=str(api_key),
            base_url=current.get("base_url"),
            temperature=float(current.get("temperature", 0.7)),
        )
    )


# ---------------------------------------------------------------------------
# 工具级自适应兜底（无 LLM，省 token）
# ---------------------------------------------------------------------------
def _strip_action_words(goal: str) -> str:
    """去掉 goal 中的动作词，剩余部分作为目标 label 特征。"""
    lowered = goal.lower()
    for word in (*_READ_WORDS, *_CLICK_WORDS, *_FILL_WORDS, *_SEND_WORDS):
        lowered = lowered.replace(word, " ")
    return " ".join(lowered.split())


class AdaptiveFallback:
    """无 LLM 兜底：重新读树 + 关键词启发式动作。

    读取类目标直接返回树（最有用的安全基线）；点击/输入类尝试宽松特征
    匹配（label 包含、文档顺序逐候选）；写操作类返回 None 升级 LLM。
    """

    def __init__(self, adapter: ToolCaller, *, max_candidates: int = 5) -> None:
        self._adapter = adapter
        self._max_candidates = max_candidates

    async def _read_tree(self) -> list[Any]:
        result = await self._adapter.call_tool("chrome_read_page", {})
        if not result.ok:
            return []
        return parse_tree(extract_tree_text(result))

    async def run(self, goal: str, args: dict[str, Any]) -> AdapterToolResult | None:
        """执行一次自适应兜底；无法确定动作返回 None（上层升级 LLM）。

        Returns:
            adapter 结果（ok=True）或 None。
        """
        goal_l = goal.lower()
        if any(word in goal_l for word in _SEND_WORDS):
            # 写操作不自动执行：交给预写例程 + 审批流（doc 14 红线）
            return None

        tree = await self._read_tree()
        if not tree:
            return None

        target_words = _strip_action_words(goal)
        if any(word in goal_l for word in _READ_WORDS):
            # 读取类：把树作为观察返回（安全基线，不产生副作用）
            return await self._adapter.call_tool("chrome_read_page", {})

        if any(word in goal_l for word in _CLICK_WORDS) and target_words:
            spec = TargetSpec(label_contains=target_words)
            for ref in match_candidates(tree, spec)[: self._max_candidates]:
                result = await self._adapter.call_tool("chrome_click_element", {"ref": ref})
                if result.ok:
                    return result
            return None

        if any(word in goal_l for word in _FILL_WORDS):
            value = args.get("value")
            if not isinstance(value, str):
                return None
            spec = TargetSpec(role="textbox")
            refs = match_candidates(tree, spec)
            if not refs:
                refs = match_candidates(tree, TargetSpec(role="input"))
            for ref in refs[: self._max_candidates]:
                result = await self._adapter.call_tool(
                    "chrome_fill_or_select", {"ref": ref, "value": value}
                )
                if result.ok:
                    return result
            return None

        return None


# ---------------------------------------------------------------------------
# LLM 动态兜底（ReAct 循环）
# ---------------------------------------------------------------------------
class LLMFallback:
    """LLM 兜底：≤ max_steps 步 ReAct（读树 -> 决策 -> 调工具 -> 观察）。"""

    def __init__(
        self,
        adapter: ToolCaller,
        llm: FallbackLLM | None,
        *,
        max_steps: int = 3,
        settings: Settings | None = None,
    ) -> None:
        self._adapter = adapter
        self._llm = llm
        self._max_steps = max_steps
        self._settings = settings or get_settings()

    async def run(self, goal: str) -> AdapterToolResult | None:
        """执行 LLM 兜底；成功返回最后观察结果，失败/无 LLM 返回 None。"""
        if self._llm is None:
            return None
        last_error: str | None = None
        last_result: AdapterToolResult | None = None
        for _step in range(self._max_steps):
            read = await self._adapter.call_tool("chrome_read_page", {})
            if not read.ok:
                last_error = f"读取页面失败: {read.error}"
                last_result = None
                continue
            summary = truncate_tree(decode_tree_text(extract_tree_text(read)), _FALLBACK_TREE_MAX_CHARS)
            try:
                decision = await self._llm.decide(
                    page_summary=summary,
                    goal=goal,
                    last_error=last_error,
                )
            except FallbackLLMError as exc:
                last_error = f"LLM 决策失败: {exc}"
                continue
            if decision.done:
                return last_result or read
            if decision.tool not in _FALLBACK_TOOLS:
                last_error = f"LLM 提议非法工具: {decision.tool}（不在兜底白名单）"
                last_result = None
                continue
            result = await self._adapter.call_tool(decision.tool, dict(decision.args))
            last_result = result
            last_error = result.error if not result.ok else None
        # 步数耗尽：若最近一次工具调用成功，把它作为观察返回（供 planner 再规划）
        return last_result if last_result is not None and last_result.ok else None
