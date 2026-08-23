"""SkillExecutor（doc 06 §5.4-5.5 / doc 07 §2）——tools/router.py 的实现。

执行顺序（用户确认的「预写 + 兜底」链路）：
1. 查 RoutineRegistry：命中 -> RoutineRunner 逐步骤执行（确定性、无 LLM、省 token）
2. 例程失败 -> 整条例程重试 N 次（默认 2，页面变化 ref 失效 -> 重读树重新匹配）
3. 重试耗尽 -> 双层兜底（可配置 browser_mcp_fallback_mode）：
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
from app.agent.tools.fallback import AdaptiveFallback, FallbackLLM, LLMFallback
from app.agent.tools.routine import Routine, RoutineRegistry
from app.agent.tools.runner import AdapterToolResult, RoutineError, RoutineRunner, ToolCaller
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_FALLBACK_MODES = frozenset({"adaptive", "llm", "both", "off"})

# adapter 返回的错误文本中命中即不可重试（白名单/授权类）
_RULE_VIOLATION_MARKERS = ("高危工具", "未知工具", "不在白名单", "白名单", "未授权")


def _map_goal_to_skill_id(_goal: str) -> str:
    """goal 关键词 -> Skill id 映射骨架。

    下一轮预写业务例程时填充：{"提取岗位"/"搜索职位" -> "boss.extract_jobs",
    "发送消息"/"回复" -> "boss.chat"}。本轮统一走 browser.generic，
    由兜底按 goal 意图处理。
    """
    return "browser.generic"


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
    ) -> None:
        self._adapter = adapter
        self._registry = registry or RoutineRegistry()
        self._locks = locks or LockManager()
        self._fallback_llm = fallback_llm
        self._settings = settings or get_settings()
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
