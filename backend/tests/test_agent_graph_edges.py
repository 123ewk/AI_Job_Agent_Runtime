"""graph/edges.py 条件边路由单测（doc 06 §6 / doc 03 决策表）。"""

from app.agent.graph import edges
from app.agent.graph.state import AgentState


def _state(**overrides: object) -> AgentState:
    """最小可用 State（路由函数只读部分字段）。"""
    base: AgentState = {
        "task_id": "T1",
        "task_type": "proactive_job",
        "thread_id": "th1",
        "conversation_id": None,
        "messages": [],
        "plan": [],
        "current_step": 0,
        "skill_calls": [],
        "tool_results": [],
        "approval_state": None,
        "error_state": None,
        "retry_count": 0,
        "memory_refs": [],
        "next_action": None,
        "current_goal": None,
        "terminal": None,
    }
    return {**base, **overrides}  # type: ignore[typeddict-item]


class TestRouteAfterPlanner:
    def test_passthrough_four_actions(self) -> None:
        # 路由返回 next_action 原值，节点名映射由 add_conditional_edges 完成
        assert edges.route_after_planner(_state(next_action="skill_call")) == "skill_call"
        assert edges.route_after_planner(_state(next_action="approval")) == "approval"
        assert edges.route_after_planner(_state(next_action="sync")) == "sync"
        assert edges.route_after_planner(_state(next_action="end")) == "end"

    def test_missing_next_action_defaults_to_end(self) -> None:
        assert edges.route_after_planner(_state(next_action=None)) == "end"


class TestRouteAfterTool:
    def test_error_takes_priority(self) -> None:
        state = _state(error_state={"kind": "dom_change"}, tool_results=[{"ok": False}])
        assert edges.route_after_tool(state) == "error_recovery"

    def test_needs_persist_routes_to_sync(self) -> None:
        state = _state(tool_results=[{"ok": True, "needs_persist": True}])
        assert edges.route_after_tool(state) == "sync"

    def test_plain_observation_back_to_planner(self) -> None:
        state = _state(tool_results=[{"ok": True, "needs_persist": False}])
        assert edges.route_after_tool(state) == "planner"


class TestRouteAfterSync:
    def test_not_ended_back_to_planner(self) -> None:
        assert edges.route_after_sync(_state(next_action="sync")) == "planner"

    def test_ended_reaches_end(self) -> None:
        assert edges.route_after_sync(_state(next_action="end")) == "end"


class TestRouteAfterRecovery:
    def test_retry_budget_left_back_to_tool_executor(self) -> None:
        assert edges.route_after_recovery(_state(retry_count=1)) == "tool_executor"
        assert edges.route_after_recovery(_state(retry_count=2)) == "tool_executor"

    def test_retry_exhausted_ends(self) -> None:
        assert edges.route_after_recovery(_state(retry_count=3)) == "end"

    def test_unrecoverable_ends_immediately(self) -> None:
        state = _state(retry_count=1, error_state={"kind": "rule_violation", "unrecoverable": True})
        assert edges.route_after_recovery(state) == "end"
