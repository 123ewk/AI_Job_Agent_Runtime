"""StateGraph 构造与编译（doc 06 §7-§9）。

拓扑照抄 doc 06 §3/§7：ReAct 主循环 planner -> skill_router -> tool_executor
-> planner，外加 approval（Interrupt）/ sync / error_recovery 分支。

- checkpointer 由调用方注入：测试传 InMemorySaver，生产由 runtime 传
  AsyncPostgresSaver（langgraph-checkpoint-postgres，runtime 阶段再引依赖）。
- planner 挂 RetryPolicy（瞬时重试 2 次，doc 06 §10）；retry_on 限定
  LLM/超时/网络类异常，DomainGuard 规则违反不在节点层重试。
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from app.agent.graph import edges
from app.agent.graph.deps import GraphRuntime, LLMPlanError
from app.agent.graph.nodes import (
    classify,
    make_approval,
    make_error_recovery,
    make_planner,
    make_receive_task,
    make_skill_router,
    make_sync,
    make_tool_executor,
)
from app.agent.graph.state import AgentState

# langgraph 内部 _Node Protocol 重载与 Callable 别名推断不兼容（直接传
# async 函数可过，工厂返回的 Callable 别名不行）；运行时完全合法，集中
# 在此收口 type: ignore，避免图装配代码散布 7 处 ignore。
AnyGraph = StateGraph[Any, Any, Any, Any]


def _add_node(graph: AnyGraph, name: str, node: Any, **kwargs: Any) -> None:  # noqa: ANN401
    graph.add_node(name, node, **kwargs)


def _is_transient(exc: Exception) -> bool:
    """RetryPolicy 只重试瞬时故障；业务/规则失败重试无意义（doc 06 §10）。"""
    return isinstance(exc, LLMPlanError | TimeoutError | ConnectionError)


def build_graph(
    runtime: GraphRuntime,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """编译完整 Agent 图。返回 langgraph CompiledStateGraph（ainvoke/astream 可用）。"""
    g: AnyGraph = StateGraph(AgentState)

    _add_node(g, "receive_task", make_receive_task(runtime))
    _add_node(g, "classify", classify)
    _add_node(g, "planner", make_planner(runtime), retry_policy=RetryPolicy(max_attempts=2, retry_on=_is_transient))
    _add_node(g, "skill_router", make_skill_router(runtime))
    _add_node(g, "tool_executor", make_tool_executor(runtime))
    _add_node(g, "approval", make_approval(runtime))
    _add_node(g, "sync", make_sync(runtime))
    _add_node(g, "error_recovery", make_error_recovery(runtime))

    g.add_edge(START, "receive_task")
    g.add_edge("receive_task", "classify")
    g.add_edge("classify", "planner")
    g.add_conditional_edges(
        "planner",
        edges.route_after_planner,
        {
            "skill_call": "skill_router",
            "approval": "approval",
            "sync": "sync",
            "end": END,
        },
    )
    g.add_edge("skill_router", "tool_executor")
    g.add_conditional_edges(
        "tool_executor",
        edges.route_after_tool,
        {
            "planner": "planner",
            "error_recovery": "error_recovery",
            "sync": "sync",
        },
    )
    g.add_conditional_edges("sync", edges.route_after_sync, {"planner": "planner", "end": END})
    g.add_edge("approval", "planner")  # resume 后回规划（doc 06 §9.2）
    g.add_conditional_edges(
        "error_recovery",
        edges.route_after_recovery,
        {"tool_executor": "tool_executor", "end": END},
    )

    return g.compile(checkpointer=checkpointer)
