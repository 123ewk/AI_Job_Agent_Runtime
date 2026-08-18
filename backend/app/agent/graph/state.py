"""AgentState 与 reducer（doc 06 §4）。

State 是 LangGraph 图中各节点共享的唯一数据载体；reducer 决定"节点返回的
部分更新"如何合并进已有 State。语义分三类：

- append：列表累积，节点只追加、不变更历史；
- append_dedup：追加并按 message_id 去重（messages 来源含 DB history 与
  实时 manual，重放/恢复时可能重复送达）；
- plan_reducer：非空更新整体替换（重规划输出的是完整新计划）；空列表
  视为"本节点未产出计划"，保持原值——LangGraph 会把显式空列表也传给
  reducer，必须区分"没更新"与"清空"。
- 未注解字段走 LangGraph 默认 last-write-wins（后写覆盖）。
"""

from collections.abc import Callable
from typing import Annotated, Any, TypedDict

Reducer = Callable[[list[Any]], list[Any]]


def append(existing: list[Any], new: list[Any]) -> list[Any]:
    """累积追加：skill_calls / tool_results / memory_refs 共用。

    传入 None 容错为空更新，避免节点漏字段时 reducer 崩溃。
    """
    if not new:
        return existing
    return [*existing, *new]


def append_dedup(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 message_id 去重追加（doc 06 §4：取代 add_messages 的原因）。

    去重键为 external_msg_id 映射后的 message_id；同 id 后到者覆盖语义
    不需要（消息不可变），直接跳过。
    """
    if not new:
        return existing
    seen = {m.get("message_id") for m in existing}
    merged = list(existing)
    for msg in new:
        mid = msg.get("message_id")
        # 无 message_id 的消息（如临时观察）不去重，直接追加
        if mid is not None and mid in seen:
            continue
        if mid is not None:
            seen.add(mid)
        merged.append(msg)
    return merged


def plan_reducer(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """计划 reducer：非空整体替换（重规划），空更新保持原值。

    planner 每次输出完整计划（doc 06 §5.3），"增量规划"由 planner 自行
    合并旧计划后整体下发，reducer 无需理解增量语义。
    """
    if not new:
        return existing
    return list(new)


class AgentState(TypedDict):
    """图全局状态（doc 06 §4，字段与语义逐项对齐）。"""

    task_id: str
    task_type: str  # proactive_job|proactive_chat|hr_reply|approval_resume|sync|recovery
    thread_id: str  # Checkpoint 线（configurable.thread_id 与此一致）
    conversation_id: str | None
    messages: Annotated[list[dict[str, Any]], append_dedup]  # 会话历史（来自 DB）
    plan: Annotated[list[dict[str, Any]], plan_reducer]
    current_step: int
    skill_calls: Annotated[list[dict[str, Any]], append]  # 累积 Skill 调用记录
    tool_results: Annotated[list[dict[str, Any]], append]  # 观察结果累积
    approval_state: dict[str, Any] | None  # {type, context, decision?}
    error_state: dict[str, Any] | None  # {node, error, retry_count, kind}
    retry_count: int
    memory_refs: Annotated[list[str], append]
    next_action: str | None  # planner 输出：skill_call|approval|sync|end
    current_goal: str | None  # 扩展字段：planner 决策的 goal（skill_router 映射依据）
    terminal: str | None  # succeeded|failed|canceled
