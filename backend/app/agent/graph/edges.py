"""条件边路由（doc 06 §6）。

纯函数：只读 State 决定下一节点，无 IO 无副作用，与 doc 03 决策表
一一对应，因此可独立单测。
"""

from app.agent.graph.state import AgentState

# 路由返回值（add_conditional_edges 的映射键）
TO_PLANNER = "planner"
TO_SKILL_ROUTER = "skill_router"
TO_APPROVAL = "approval"
TO_SYNC = "sync"
TO_ERROR_RECOVERY = "error_recovery"
TO_TOOL_EXECUTOR = "tool_executor"
TO_END = "end"


def route_after_planner(state: AgentState) -> str:
    """planner 出口：next_action 直通（skill_call|approval|sync|end）。"""
    return state.get("next_action") or TO_END


def route_after_tool(state: AgentState) -> str:
    """tool_executor 出口：错误优先，其次落库转 sync，否则回 planner 再规划。"""
    if state.get("error_state"):
        return TO_ERROR_RECOVERY
    results = state.get("tool_results") or []
    if results and results[-1].get("needs_persist"):
        return TO_SYNC
    return TO_PLANNER


def route_after_sync(state: AgentState) -> str:
    """sync 出口：planner 未宣示结束则回规划继续 ReAct 循环。"""
    if state.get("next_action") == "end":
        return TO_END
    return TO_PLANNER


def route_after_recovery(state: AgentState) -> str:
    """error_recovery 出口：重试耗尽或不可恢复 -> 终态 failed（doc 06 §10）。"""
    error_state = state.get("error_state") or {}
    if state.get("retry_count", 0) > 2 or error_state.get("unrecoverable"):
        return TO_END
    return TO_TOOL_EXECUTOR
