"""StateGraph 构造与编译（doc 06 §7-§9）。

拓扑照抄 doc 06 §3/§7：ReAct 主循环 planner -> skill_router -> tool_executor
-> planner，外加 approval（Interrupt）/ sync / error_recovery 分支。

- checkpointer 由调用方注入：测试传 InMemorySaver，生产由 runtime 传
  AsyncPostgresSaver（langgraph-checkpoint-postgres，runtime 阶段再引依赖）。
- planner 挂 RetryPolicy（瞬时重试 2 次，doc 06 §10）；retry_on 限定
  LLM/超时/网络类异常，DomainGuard 规则违反不在节点层重试。
"""

import inspect
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
from app.agent.runtime.ws_hub import emit_task_step

# langgraph 内部 _Node Protocol 重载与 Callable 别名推断不兼容（直接传
# async 函数可过，工厂返回的 Callable 别名不行）；运行时完全合法，集中
# 在此收口 type: ignore，避免图装配代码散布 7 处 ignore。
AnyGraph = StateGraph[Any, Any, Any, Any]

# state 缺 user_id 时的 task.step 广播兜底（receive_task 正常会写；单用户 V1 固定 1）
_FALLBACK_USER_ID = 1


def _step_detail(out: dict[str, Any]) -> str | None:
    """从节点部分更新里提取一句可读 detail 供 task.step 展示（纯观测，失败置 None）。"""
    if out.get("error_state"):
        return str(out["error_state"].get("error") or "error")
    if out.get("current_goal"):
        return str(out["current_goal"])
    if out.get("terminal"):
        return str(out["terminal"])
    return None


def _add_node(graph: AnyGraph, name: str, node: Any, **kwargs: Any) -> None:  # noqa: ANN401
    """注册节点并包一层 task.step 事件广播（doc 12 节点级实时执行路径）。

    wrapper 在执行前发 ``running``、成功后发 ``done``、异常时发 ``failed`` 后
    re-raise。emit 走 ws_hub（无订阅为静默 no-op），不改变节点返回值/异常语义——
    仅观测，绝不因广播失败影响图执行。

    兼容同步/异步节点：``classify`` 这类既存同步节点不 await 调用，LangGraph
    本就在不同执行器路径里统一调用；wrapper 只包异步节点（langgraph 会切线程执行同步）。
    """
    is_async = inspect.iscoroutinefunction(node)

    async def _stepped(state: AgentState) -> dict[str, Any]:
        # 真实 DB 主键恒数字；测试可能用非数字字符串（如 "T1"），无法 int 时回退 0
        # 只走用户通道推送，避免破坏既有 flow 断言（无订阅时本就 no-op）。
        try:
            task_id = int(state["task_id"])
        except (TypeError, ValueError):
            task_id = 0
        user_id = state.get("user_id", _FALLBACK_USER_ID)
        await emit_task_step(task_id, user_id, name, "running")
        out: dict[str, Any]
        try:
            out = await node(state) if is_async else node(state)
        except Exception as exc:
            await emit_task_step(task_id, user_id, name, "failed", detail=str(exc))
            raise
        await emit_task_step(task_id, user_id, name, "done", detail=_step_detail(out))
        return out

    graph.add_node(name, _stepped, **kwargs)


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
