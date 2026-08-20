"""WorkflowEngine 单元测试（doc 04 §5 生命周期 + GraphRuntime 生产实现）。

不连 DB / 不连 LLM / 不连 MCP：四个 DB 边界方法（引擎设计的注入点）覆写为
内存 Fake，覆盖 run -> suspend(Interrupt) -> resume -> terminal 全周期、
执行锁的挂起保持语义、未接线依赖的 fail-fast 行为。
"""

from types import SimpleNamespace
from typing import Any, NoReturn
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph.deps import (
    PlannerContext,
    PlannerDecision,
    PlannerLike,
    SkillCall,
    SkillExecutorLike,
    TaskInfo,
    ToolResult,
)
from app.agent.graph.state import AgentState
from app.agent.runtime.lock_manager import LockManager
from app.agent.runtime.workflow_engine import (
    EngineStateError,
    PersistFn,
    RecoverFn,
    WorkflowEngine,
)
from app.models.task import Task, TaskStatus
from app.schema.enums import ApprovalType


class FakeLLM:
    """脚本化 planner：按预设序列吐决策，耗尽后结束。"""

    def __init__(self, decisions: list[PlannerDecision]) -> None:
        self._decisions = list(decisions)

    async def plan(self, ctx: PlannerContext) -> PlannerDecision:  # noqa: ARG002
        if self._decisions:
            return self._decisions.pop(0)
        return PlannerDecision(action="end")


class ExplodingLLM:
    """永远抛非瞬时异常的 planner：验证引擎崩溃收尾路径。"""

    async def plan(self, ctx: PlannerContext) -> PlannerDecision:  # noqa: ARG002
        msg = "llm down"
        raise RuntimeError(msg)


class FakeSkills:
    """脚本化 Skill 执行。"""

    def __init__(self, result: ToolResult | None = None) -> None:
        self._result = result
        self.executed: list[SkillCall] = []

    def map_goal_to_skill(self, goal: str) -> SkillCall:
        return SkillCall(skill="boss.extract_jobs", args={}, goal=goal)

    async def execute(self, call: SkillCall) -> ToolResult:
        self.executed.append(call)
        return self._result or ToolResult(ok=True, data={}, skill=call.skill)


class _UnusedSessionFactory:
    """占位 session 工厂：DB 边界全部被覆写，触达即测试失败。"""

    def __call__(self) -> NoReturn:
        msg = "session_factory must not be touched in engine tests"
        raise AssertionError(msg)


_UNSET = object()  # 哨兵：区分"未传 thread_id（生成 uuid）"与"显式 None（脏数据回退）"


def _task_row(task_id: int = 7, *, thread_id: object = _UNSET, conversation_id: int | None = None) -> Any:  # noqa: ANN401
    return SimpleNamespace(
        id=task_id,
        user_id=1,
        thread_id=uuid4() if thread_id is _UNSET else thread_id,
        type="proactive_job",
        conversation_id=conversation_id,
    )


class FakeEngine(WorkflowEngine):
    """覆写 DB 边界的引擎（内存版任务行/消息/状态/审批记录）。"""

    def __init__(
        self,
        llm: PlannerLike,
        *,
        skills: SkillExecutorLike | None = None,
        task_row: Any = None,  # noqa: ANN401 - SimpleNamespace 伪 Task 行
        messages: list[Any] | None = None,
        persist_fn: PersistFn | None = None,
        recover_fn: RecoverFn | None = None,
    ) -> None:
        self.locks = LockManager()
        self.task_row = task_row or _task_row()
        self.messages = messages or []
        self.status_calls: list[tuple[int, str, str | None]] = []
        self.approvals: list[tuple[int, int, str]] = []
        super().__init__(
            llm,
            skills=skills,
            checkpointer=InMemorySaver(),
            locks=self.locks,
            session_factory=_UnusedSessionFactory(),  # type: ignore[arg-type]
            persist_fn=persist_fn,
            recover_fn=recover_fn,
        )

    async def _fetch_task(self, task_id: str) -> Task:  # type: ignore[override]  # noqa: ARG002
        return self.task_row

    async def _fetch_messages(self, conversation_id: int) -> list[Any]:  # type: ignore[override]  # noqa: ARG002
        return self.messages

    async def _set_task_status(  # type: ignore[override]
        self, task_id: int, status: TaskStatus, *, error_message: str | None = None
    ) -> None:
        self.status_calls.append((task_id, status.value, error_message))

    async def _create_approval_record(  # type: ignore[override]
        self,
        task_id: int,
        user_id: int,
        approval_type: ApprovalType,
        payload: dict[str, Any],  # noqa: ARG002 - 覆写签名对齐，值由断言另行覆盖
    ) -> str:
        self.approvals.append((task_id, user_id, approval_type.value))
        return "101"


async def test_run_happy_path_marks_succeeded_and_releases_lock() -> None:
    """直接 end 的任务：pending->running->succeeded，终态释放执行锁。"""
    engine = FakeEngine(FakeLLM([PlannerDecision(action="end")]))

    result = await engine.run("7")

    assert result["terminal"] == "succeeded"
    assert [s[1] for s in engine.status_calls] == ["running", "succeeded"]
    assert not engine.locks.execution_locked


async def test_run_suspends_on_approval_then_resume_completes() -> None:
    """Interrupt 挂起：waiting_approval + 锁保持；resume 后终态 + 释放锁。"""
    llm = FakeLLM(
        [
            PlannerDecision(action="skill_call", goal="回复期望薪资", needs_approval=True, approval_type="salary"),
            PlannerDecision(action="end"),
        ]
    )
    engine = FakeEngine(llm)
    thread_id = str(engine.task_row.thread_id)

    result = await engine.run("7")

    assert "__interrupt__" in result
    assert engine.approvals == [(7, 1, "salary")]  # 类型收敛到 doc 14 七类
    assert [s[1] for s in engine.status_calls] == ["running", "waiting_approval"]
    assert engine.locks.execution_locked  # 挂起期间锁不释放（doc 04 §8.1 V1）

    result2 = await engine.resume(thread_id, "approve")

    assert result2["terminal"] == "succeeded"
    assert [s[1] for s in engine.status_calls] == ["running", "waiting_approval", "running", "succeeded"]
    assert not engine.locks.execution_locked


async def test_resume_without_suspension_rejected() -> None:
    """未挂起的引擎 resume 属误用：拒绝且不影响锁状态。"""
    engine = FakeEngine(FakeLLM([]))
    with pytest.raises(EngineStateError):
        await engine.resume(str(uuid4()), "approve")


async def test_unknown_approval_type_fails_fast_and_aborts() -> None:
    """planner 输出 doc 14 之外的审批类型：ValueError -> 任务 failed + 释放锁。"""
    llm = FakeLLM(
        [PlannerDecision(action="skill_call", goal="发送消息", needs_approval=True, approval_type="send_message")]
    )
    engine = FakeEngine(llm)

    with pytest.raises(ValueError, match="非法审批类型"):
        await engine.run("7")

    assert engine.status_calls[-1][1] == "failed"
    assert not engine.locks.execution_locked


async def test_run_crash_marks_failed_and_releases_lock() -> None:
    """图执行异常：原始异常上抛，任务标 failed，锁必须释放（防死锁）。"""
    engine = FakeEngine(ExplodingLLM())

    with pytest.raises(RuntimeError, match="llm down"):
        await engine.run("7")

    assert engine.status_calls[-1][1] == "failed"
    assert not engine.locks.execution_locked


async def test_unwired_dependencies_fail_fast() -> None:
    """未接线依赖 fail-fast：skills/persist 抛明确异常；recover 返回 False。"""
    engine = FakeEngine(FakeLLM([]))

    with pytest.raises(EngineStateError, match="SkillExecutor"):
        _ = engine.skills
    with pytest.raises(EngineStateError, match="SyncService"):
        await engine.persist({})
    assert await engine.recover_browser({"error": "dom"}) is False


async def test_wired_recover_and_persist_pass_through() -> None:
    """已接线依赖透传：recover_fn 结果原样返回；persist_fn 收到图 state。"""
    calls: list[AgentState] = []

    async def recover(error_state: dict[str, Any]) -> bool:  # noqa: ARG001
        return True

    async def persist(state: AgentState) -> None:
        calls.append(state)

    engine = FakeEngine(FakeLLM([]), recover_fn=recover)
    assert await engine.recover_browser({"error": "dom"}) is True

    llm = FakeLLM([PlannerDecision(action="skill_call", goal="提取岗位"), PlannerDecision(action="end")])
    persisted: list[AgentState] = []

    async def persist_state(state: AgentState) -> None:
        persisted.append(state)

    engine2 = FakeEngine(
        llm,
        skills=FakeSkills(
            result=ToolResult(ok=True, data={"created": 3}, needs_persist=True, skill="boss.extract_jobs")
        ),
        persist_fn=persist_state,
    )
    result = await engine2.run("7")
    assert result["terminal"] == "succeeded"
    assert len(persisted) == 1  # needs_persist -> sync 恰好落库一次
    assert calls == []


async def test_load_task_and_list_messages_conversion() -> None:
    """DB 行 -> 图 DTO 转换：id 字符串化、role->sender、thread_id 缺失回退。"""
    engine = FakeEngine(
        FakeLLM([]),
        task_row=_task_row(9, thread_id=None, conversation_id=5),  # 脏数据：无 thread_id
        messages=[SimpleNamespace(id=1, role="hr", content="你好")],
    )

    info = await engine.load_task("9")
    assert info == TaskInfo(task_id="9", task_type="proactive_job", thread_id="task-9", conversation_id="5")

    msgs = await engine.list_messages("5")
    assert msgs == [{"message_id": "1", "sender": "hr", "text": "你好"}]
