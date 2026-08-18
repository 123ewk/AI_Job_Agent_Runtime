"""图节点实现（doc 06 §5）。

依赖注入采用工厂闭包（doc 06 §5 指定的两种方式之一）：make_xxx(runtime)
返回符合 LangGraph 签名 `async def node(state) -> dict` 的节点函数，返回
值为部分 State 更新，由 reducer 合并。测试/生产传不同 runtime 即可。

异常分工（doc 06 §10）：
- LLM 瞬时故障：planner 抛 LLMPlanError -> 编译期 RetryPolicy 同节点重试；
- 工具/DOM 故障：tool_executor 捕获转 error_state -> 条件边进 error_recovery。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.agent.graph.deps import (
    ERROR_KIND_DOM_CHANGE,
    ERROR_KIND_RULE_VIOLATION,
    ERROR_KIND_TIMEOUT,
    GraphRuntime,
    PlannerContext,
    PlannerDecision,
    SkillCall,
    ToolResult,
)
from app.agent.graph.state import AgentState

logger = logging.getLogger(__name__)

# 节点函数类型别名（LangGraph 签名：state 进、部分更新 dict 出）
NodeFunc = Callable[[AgentState], Awaitable[dict[str, Any]]]

# 合法 Approval 决策（doc 14）；非法值按 deny 处理（doc 06 §15）
_VALID_DECISIONS = {"approve", "deny", "timeout"}


# ---------------------------------------------------------------------------
# 5.1 receive_task：装载任务元数据与 DB 会话历史
# ---------------------------------------------------------------------------
def make_receive_task(runtime: GraphRuntime) -> NodeFunc:
    async def receive_task(state: AgentState) -> dict[str, Any]:
        task = await runtime.load_task(state["task_id"])
        msgs: list[dict[str, Any]] = []
        if task.conversation_id:
            msgs = await runtime.list_messages(task.conversation_id)
        return {
            "task_type": task.task_type,
            "thread_id": task.thread_id,
            "conversation_id": task.conversation_id,
            "messages": msgs,
        }

    return receive_task


# ---------------------------------------------------------------------------
# 5.2 classify：硬编码领域分支（垂直 Agent，不调 LLM）
# ---------------------------------------------------------------------------
_KNOWN_TASK_TYPES = frozenset({"proactive_job", "proactive_chat", "hr_reply", "approval_resume", "sync", "recovery"})


def classify(state: AgentState) -> dict[str, Any]:
    """校验并归一 task_type；未知类型按 recovery 走恢复分支（保守安全）。"""
    task_type = state.get("task_type", "")
    if task_type not in _KNOWN_TASK_TYPES:
        logger.warning("Unknown task_type, fallback to recovery", extra={"task_type": task_type})
        task_type = "recovery"
    return {"task_type": task_type}


# ---------------------------------------------------------------------------
# 5.3 planner：ReAct 核心，LLM 决策下一动作
# ---------------------------------------------------------------------------
def make_planner(runtime: GraphRuntime) -> NodeFunc:
    async def planner(state: AgentState) -> dict[str, Any]:
        results = state.get("tool_results") or []
        approval_state = state.get("approval_state") or {}
        ctx = PlannerContext(
            task_type=state["task_type"],
            messages=state.get("messages") or [],
            plan=state.get("plan") or [],
            current_step=state.get("current_step", 0),
            recent_result=results[-1] if results else None,
            approval_decision=approval_state.get("decision"),
        )
        # LLM 失败不在此捕获：抛 LLMPlanError 交给 RetryPolicy 瞬时重试
        decision: PlannerDecision = await runtime.llm.plan(ctx)

        if decision.needs_approval:
            return {
                "next_action": "approval",
                "approval_state": {"type": decision.approval_type, "context": {"goal": decision.goal}},
            }
        update: dict[str, Any] = {"next_action": decision.action, "plan": decision.plan, "current_goal": decision.goal}
        if decision.action == "end":
            update["terminal"] = "succeeded"
        return update

    return planner


# ---------------------------------------------------------------------------
# 5.4 skill_router：目标 -> Skill + 入参
# ---------------------------------------------------------------------------
def make_skill_router(runtime: GraphRuntime) -> NodeFunc:
    async def skill_router(state: AgentState) -> dict[str, Any]:
        # goal 由 planner 写入 current_goal；缺失时回退 next_action（保底不崩）
        goal = state.get("current_goal") or state.get("next_action") or ""
        call: SkillCall = runtime.skills.map_goal_to_skill(goal)
        return {"skill_calls": [{"skill": call.skill, "args": call.args, "goal": call.goal}]}

    return skill_router


# ---------------------------------------------------------------------------
# 5.5 tool_executor：执行 Skill，失败转 error_state（不抛出）
# ---------------------------------------------------------------------------
def _classify_exception(exc: Exception) -> str:
    """异常 -> error kind。adapter 可自带 error_kind 属性自声明（doc 07）。"""
    declared = getattr(exc, "error_kind", None)
    if declared:
        return str(declared)
    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return ERROR_KIND_TIMEOUT
    if isinstance(exc, PermissionError | ValueError):
        # DomainGuard 拒绝以 ValueError 语义上抛（域规则违反，不可重试）
        return ERROR_KIND_RULE_VIOLATION
    # 浏览器操作未知失败默认 DOM/页面异常，走 browser_recovery 可恢复路径
    return ERROR_KIND_DOM_CHANGE


def make_tool_executor(runtime: GraphRuntime) -> NodeFunc:
    async def tool_executor(state: AgentState) -> dict[str, Any]:
        calls = state.get("skill_calls") or []
        if not calls:
            return {
                "error_state": {
                    "node": "tool_executor",
                    "error": "no skill_call pending",
                    "kind": ERROR_KIND_RULE_VIOLATION,
                }
            }
        last = calls[-1]
        call = SkillCall(skill=last.get("skill", ""), args=last.get("args") or {}, goal=last.get("goal", ""))
        try:
            result: ToolResult = await runtime.skills.execute(call)
        except Exception as exc:
            kind = _classify_exception(exc)
            logger.warning("Skill execution failed", extra={"skill": call.skill, "kind": kind, "error": str(exc)})
            failed = ToolResult(ok=False, error=str(exc), error_kind=kind, skill=call.skill).to_state()
            return {
                "tool_results": [failed],
                "error_state": {"node": "tool_executor", "error": str(exc), "kind": kind},
            }
        return {"tool_results": [result.to_state()], "error_state": None, "retry_count": 0}

    return tool_executor


# ---------------------------------------------------------------------------
# 5.6 approval：Interrupt 暂停，Command(resume) 注入决策
# ---------------------------------------------------------------------------
def make_approval(runtime: GraphRuntime) -> NodeFunc:
    from langgraph.types import interrupt  # 局部导入：仅此节点触发暂停语义

    async def approval(state: AgentState) -> dict[str, Any]:
        approval_state = state.get("approval_state") or {}
        approval_id = await runtime.create_approval(approval_state)
        decision = interrupt({"approval_id": approval_id, "context": approval_state})
        if decision not in _VALID_DECISIONS:
            # 非法 resume 值按 deny 处理，不中断图（doc 06 §15）
            logger.warning("Invalid approval decision, treating as deny", extra={"decision": decision})
            decision = "deny"
        return {"approval_state": {**approval_state, "decision": decision}}

    return approval


# ---------------------------------------------------------------------------
# 5.7 sync：落库（doc 13 SyncService）
# ---------------------------------------------------------------------------
def make_sync(runtime: GraphRuntime) -> NodeFunc:
    async def sync(state: AgentState) -> dict[str, Any]:
        await runtime.persist(state)
        return {}

    return sync


# ---------------------------------------------------------------------------
# 5.8 error_recovery：分类恢复 + retry_count 递增（doc 06 §11）
# ---------------------------------------------------------------------------
def make_error_recovery(runtime: GraphRuntime) -> NodeFunc:
    async def error_recovery(state: AgentState) -> dict[str, Any]:
        error_state = state.get("error_state") or {}
        kind = error_state.get("kind")
        retry_count = state.get("retry_count", 0) + 1
        update: dict[str, Any] = {"retry_count": retry_count}

        if kind == ERROR_KIND_RULE_VIOLATION:
            # 规则违反（DomainGuard 拒绝）不重试，直接终态（doc 06 §16）
            update["error_state"] = {**error_state, "unrecoverable": True}
            update["terminal"] = "failed"
            return update

        if retry_count > 2:
            # 恢复 Retry 耗尽（doc 06 §10 上限 2）；必须先于 dom_change 分支，
            # 否则"恢复成功但已耗尽"会提前 return 丢失 terminal=failed
            update["terminal"] = "failed"
            return update

        if kind == ERROR_KIND_DOM_CHANGE:
            recovered = await runtime.recover_browser(error_state)
            if not recovered:
                update["error_state"] = {**error_state, "unrecoverable": True}
                update["terminal"] = "failed"
                return update
            # 恢复成功：清 error_state，回 tool_executor 重试
            update["error_state"] = None
        return update

    return error_recovery
