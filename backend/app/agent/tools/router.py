"""SkillExecutor（doc 06 §5.4-5.5 / doc 07 §2）——tools/router.py 的实现。

执行顺序（用户确认的「派发 + 预写 + 兜底」链路）：
1. 垂直服务派发：skill=boss.chat/boss.extract_jobs -> 注入的垂直服务
   （chrome_javascript 注入；send 走 approved 红线，未接线报错而非退化）
2. 查 RoutineRegistry：命中 -> RoutineRunner 逐步骤执行（确定性、无 LLM、省 token；
   只读例程由默认 registry 内置注册，当前无——Boss 加载更多无安全只读实现，见 builtin_routines）
3. 例程失败 -> 整条例程重试 N 次（默认 2，页面变化 ref 失效 -> 重读树重新匹配）
4. 重试耗尽 -> 双层兜底（可配置 browser_mcp_fallback_mode）：
   - 工具级自适应（无 LLM，宽松特征匹配）
   - LLM 动态操作（ReAct ≤ max_steps 步，复用 planner 同款结构化输出）

浏览器锁在 execute 入口统一持有（doc 04 §8.4），例程与兜底共用同一把锁，
避免嵌套获取死锁。未接线（浏览器桥关闭）时 execute 返回明确错误而非崩溃。
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.graph.deps import (
    ERROR_KIND_DOM_CHANGE,
    ERROR_KIND_RULE_VIOLATION,
    ERROR_KIND_TIMEOUT,
    SkillCall,
    ToolResult,
)
from app.agent.runtime.lock_manager import LockManager, LockTimeoutError
from app.agent.tools.builtin_routines import builtin_readonly_routines
from app.agent.tools.fallback import AdaptiveFallback, FallbackLLM, LLMFallback
from app.agent.tools.routine import Routine, RoutineRegistry
from app.agent.tools.runner import AdapterToolResult, RoutineError, RoutineRunner, ToolCaller
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_FALLBACK_MODES = frozenset({"adaptive", "llm", "both", "off"})

# adapter 返回的错误文本中命中即不可重试（白名单/授权类）
_RULE_VIOLATION_MARKERS = ("高危工具", "未知工具", "不在白名单", "白名单", "未授权")

# ---------------------------------------------------------------------------
# goal 关键词 -> Skill id 映射（预写业务例程内容，第 4 项）
# ---------------------------------------------------------------------------
_EXTRACT_KEYWORDS = ("提取岗位", "搜索职位", "抓取岗位", "拉取职位", "解析岗位", "更新岗位")
_CHAT_KEYWORDS = ("发送消息", "发消息", "发送", "回复", "拉取消息", "读取聊天", "同步会话", "查看会话")


def _map_goal_to_skill_id(goal: str) -> str:
    """goal 关键词 -> Skill id。

    命中关键词则派发到垂直服务（boss.extract_jobs / boss.chat）；否则回退
    browser.generic（例程 → 双层兜底，均只读、不自动写操作，见 _dispatch_chat 的
    approved 门控）。「加载更多/翻页/滚动」刻意不映射：Boss 岗位列表为无限滚动无翻页
    按钮（逆向文档），且滚动加载=新请求=违反只读红线，无安全自动只读实现，故回退 generic。
    """
    g = goal.lower()
    if any(k in g for k in _EXTRACT_KEYWORDS):
        return "boss.extract_jobs"
    if any(k in g for k in _CHAT_KEYWORDS):
        return "boss.chat"
    return "browser.generic"


# boss.chat 操作意图关键词（goal 子串 → operation：list/messages/send）
_CHAT_SEND_WORDS = ("发送", "回复")
_CHAT_LIST_WORDS = ("同步", "会话", "列表")
_CHAT_MESSAGES_WORDS = ("拉取", "读取", "查看", "历史")


def _derive_chat_operation(goal: str) -> str:
    """从 goal 推测 chat operation；默认 messages（只读更安全，避免误触发写操作）。"""
    g = goal.lower()
    if any(w in g for w in _CHAT_SEND_WORDS):
        return "send"
    if any(w in g for w in _CHAT_LIST_WORDS):
        return "list"
    if any(w in g for w in _CHAT_MESSAGES_WORDS):
        return "messages"
    return "messages"


class SkillExecutor:
    """SkillExecutorLike 实现：例程主路径 + 双层兜底 + 浏览器锁。"""

    def __init__(
        self,
        *,
        adapter: ToolCaller | None,
        registry: RoutineRegistry | None = None,
        locks: LockManager | None = None,
        fallback_llm: FallbackLLM | None = None,
        settings: Settings | None = None,
        chat_service: Any | None = None,  # noqa: ANN401 - 垂直服务 duck-typing（BossChatService 鸭子类型）
        extract_service: Any | None = None,  # noqa: ANN401 - BossExtractService 鸭子类型
    ) -> None:
        self._adapter = adapter
        if registry is None:
            # 自建 registry：自动注册内置只读例程；注入的 registry 由调用方决定注册
            registry = RoutineRegistry()
            for routine in builtin_readonly_routines():
                registry.register(routine)
        self._registry = registry
        self._locks = locks or LockManager()
        self._fallback_llm = fallback_llm
        self._settings = settings or get_settings()
        # 垂直服务派发（duck-typing；None = 未接线，命中则报错而非退化）
        self._chat_service = chat_service
        self._extract_service = extract_service
        self._runner = RoutineRunner(adapter) if adapter is not None else None
        self._adaptive = AdaptiveFallback(adapter) if adapter is not None else None
        self._llm_fallback = (
            LLMFallback(
                adapter,
                fallback_llm,
                max_steps=self._settings.browser_mcp_fallback_max_steps,
                settings=self._settings,
            )
            if adapter is not None
            else None
        )

    # ------------------------------------------------------------------
    # SkillExecutorLike 协议（deps.py）
    # ------------------------------------------------------------------
    def map_goal_to_skill(self, goal: str) -> SkillCall:
        """目标描述 -> SkillCall（goal 原样透传，供兜底按意图处理）。"""
        return SkillCall(skill=_map_goal_to_skill_id(goal), args={"goal": goal}, goal=goal)

    async def execute(self, call: SkillCall) -> ToolResult:
        """执行 Skill：例程 -> 重试 -> 双层兜底，统一转图内 ToolResult。"""
        goal = call.goal or str((call.args or {}).get("goal") or "")
        if self._adapter is None or self._runner is None:
            msg = "浏览器桥未启用（BROWSER_MCP_ENABLED=false），无法执行浏览器 Skill"
            return self._failed(call.skill, msg, ERROR_KIND_RULE_VIOLATION)
        try:
            async with self._locks.browser():
                dispatched = await self._dispatch(call)
                if dispatched is not None:
                    return dispatched
                routine = self._registry.get_by_skill(call.skill)
                if routine is not None:
                    result = await self._run_routine(routine, call.args or {}, call.skill)
                    if result is not None:
                        return result
                return await self._run_fallback(goal, call.args or {}, call.skill)
        except LockTimeoutError as exc:
            msg = f"获取浏览器锁超时: {exc}"
            return self._failed(call.skill, msg, ERROR_KIND_TIMEOUT)
        except RoutineError as exc:
            msg = f"例程执行失败: {exc}"
            return self._failed(call.skill, msg, ERROR_KIND_DOM_CHANGE)
        except Exception as exc:
            logger.exception("skill execute unexpected error", extra={"skill": call.skill, "goal": goal})
            msg = f"Skill 执行异常: {exc}"
            return self._failed(call.skill, msg, ERROR_KIND_DOM_CHANGE)

    # ------------------------------------------------------------------
    # 垂直服务派发（boss.chat / boss.extract_jobs）
    # ------------------------------------------------------------------
    async def _dispatch(self, call: SkillCall) -> ToolResult | None:
        """按 skill 派发到垂直服务；非垂直 skill 返回 None（走例程/兜底）。

        服务未接线时返回明确失败（RuleViolation），不静默退化到通用兜底——
        退化会把垂直意图误判为普通浏览，比直接报错更糟（现状 gap）。
        """
        if call.skill == "boss.chat":
            if self._chat_service is None:
                return self._failed(
                    call.skill,
                    "垂直服务未接线：boss.chat（缺少 chat_service 注入）",
                    ERROR_KIND_RULE_VIOLATION,
                )
            return await self._dispatch_chat(call)
        if call.skill == "boss.extract_jobs":
            if self._extract_service is None:
                return self._failed(
                    call.skill,
                    "垂直服务未接线：boss.extract_jobs（缺少 extract_service 注入）",
                    ERROR_KIND_RULE_VIOLATION,
                )
            return await self._dispatch_extract(call)
        return None

    async def _dispatch_chat(self, call: SkillCall) -> ToolResult:
        """派发到 BossChatService.run；send 走 approved 红线（dispatch 层不新增自动审批）。"""
        args = call.args or {}
        operation = str(args.get("operation") or _derive_chat_operation(call.goal or ""))
        user_id = int(args.get("user_id", 1))
        approved = bool(args.get("approved", False))
        result = await self._chat_service.run(
            user_id=user_id,
            operation=operation,
            approved=approved,
            text=args.get("text"),
            external_id=args.get("external_id"),
        )
        # 红线：send 未审批 = 规则违规（无论 service 返回什么文本，彻底不可重试）
        if operation == "send" and not approved:
            error = getattr(result, "error", None) or "发送未被审批（approved=False）"
            return self._failed(call.skill, error, ERROR_KIND_RULE_VIOLATION)
        return self._skill_result_to_graph(result, call.skill)

    async def _dispatch_extract(self, call: SkillCall) -> ToolResult:
        """派发到 BossExtractService.run（提取 → 筛选 → 落库）。"""
        args = call.args or {}
        user_id = int(args.get("user_id", 1))
        result = await self._extract_service.run(
            user_id=user_id,
            source=str(args.get("source", "page")),
            jobs=args.get("jobs"),
            rules_override=args.get("rules_override"),
            ingest=bool(args.get("ingest", True)),
            limit=int(args.get("limit", 15)),
        )
        return self._skill_result_to_graph(result, call.skill)

    @staticmethod
    def _skill_result_to_graph(result: Any, skill: str) -> ToolResult:  # noqa: ANN401 - 垂直服务返回结果 duck-typings
        """垂直服务 SkillResult{ok,data,error} -> 图内 ToolResult。

        鸭子类型（两技能各自定义 SkillResult）；失败按文本分类 error_kind。
        """
        if getattr(result, "ok", False):
            return ToolResult(ok=True, data=getattr(result, "data", None), error=None, error_kind=None, skill=skill)
        error = getattr(result, "error", None) or "垂直工具执行失败"
        return ToolResult(
            ok=False,
            data=getattr(result, "data", None),
            error=error,
            error_kind=_classify_error(error),
            skill=skill,
        )

    # ------------------------------------------------------------------
    # 例程主路径
    # ------------------------------------------------------------------
    async def _run_routine(self, routine: Routine, args: dict[str, Any], skill: str) -> ToolResult | None:
        """执行例程（重试 routine.retry 次）。

        Returns:
            ToolResult 或 None（重试耗尽且例程允许兜底 -> 触发兜底）。
        """
        runner = self._runner
        assert runner is not None, "execute 已保证 adapter 非空时 runner 非空"
        for attempt in range(routine.retry + 1):
            try:
                result = await runner.run(routine, args)
            except RoutineError as exc:
                if attempt < routine.retry:
                    logger.warning(
                        "routine_retry",
                        extra={"routine": routine.id, "attempt": attempt + 1, "error": str(exc)},
                    )
                    continue
                if not routine.fallback:
                    msg = f"例程 {routine.id} 重试耗尽且不允许兜底: {exc}"
                    return self._failed(skill, msg, ERROR_KIND_DOM_CHANGE)
                logger.warning(
                    "routine_failed_fallback",
                    extra={"routine": routine.id, "error": str(exc)},
                )
                return None
            return self._to_graph_result(result, skill)
        return None  # 理论不可达（循环内必然 return 或抛异常）

    # ------------------------------------------------------------------
    # 双层兜底
    # ------------------------------------------------------------------
    async def _run_fallback(self, goal: str, args: dict[str, Any], skill: str) -> ToolResult:
        mode = self._settings.browser_mcp_fallback_mode
        if mode not in _FALLBACK_MODES:
            logger.warning("invalid_fallback_mode", extra={"mode": mode})
            mode = "both"

        if mode == "off":
            msg = "无预写例程且兜底已关闭（browser_mcp_fallback_mode=off）"
            return self._failed(skill, msg, ERROR_KIND_DOM_CHANGE)

        if mode in ("adaptive", "both") and self._adaptive is not None:
            result = await self._adaptive.run(goal, args)
            if result is not None:
                return self._to_graph_result(result, skill)

        if mode in ("llm", "both"):
            if self._llm_fallback is not None:
                result = await self._llm_fallback.run(goal)
                if result is not None:
                    return self._to_graph_result(result, skill)
            msg = "LLM 兜底未能完成目标（步骤耗尽或未配置 LLM）"
            return self._failed(skill, msg, ERROR_KIND_DOM_CHANGE)

        msg = "兜底未能完成目标"
        return self._failed(skill, msg, ERROR_KIND_DOM_CHANGE)

    # ------------------------------------------------------------------
    # 结果转换
    # ------------------------------------------------------------------
    @staticmethod
    def _to_graph_result(result: AdapterToolResult, skill: str) -> ToolResult:
        """adapter 结果 -> 图内 ToolResult；失败按文本分类 error_kind。"""
        if result.ok:
            return ToolResult(ok=True, data=result.data, error=None, error_kind=None, skill=skill)
        error = result.error or "工具调用失败"
        return ToolResult(
            ok=False,
            data=result.data,
            error=error,
            error_kind=_classify_error(error),
            skill=skill,
        )

    @staticmethod
    def _failed(skill: str, error: str, kind: str) -> ToolResult:
        return ToolResult(ok=False, data=None, error=error, error_kind=kind, skill=skill)


def _classify_error(error: str) -> str:
    """adapter 错误文本 -> error_kind（白名单/授权类不可重试）。"""
    if any(marker in error for marker in _RULE_VIOLATION_MARKERS):
        return ERROR_KIND_RULE_VIOLATION
    if "timeout" in error.lower() or "超时" in error:
        return ERROR_KIND_TIMEOUT
    return ERROR_KIND_DOM_CHANGE
