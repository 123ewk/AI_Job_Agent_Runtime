"""graph 全链路流程测试（doc 06 §3 拓扑：FakeRuntime + InMemorySaver）。

不连 DB / 不连 LLM / 不连 MCP：GraphRuntime 协议用脚本化 Fake 实现，
验证图编排本身（节点顺序、Interrupt/Resume、双层 Retry 终态）。
"""

from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent.graph.builder import build_graph
from app.agent.graph.deps import PlannerContext, PlannerDecision, SkillCall, TaskInfo, ToolResult


class FakeLLM:
    """脚本化 planner：按预设序列吐决策，耗尽后结束。"""

    def __init__(self, decisions: list[PlannerDecision]) -> None:
        self._decisions = list(decisions)
        self.calls = 0

    async def plan(self, ctx: PlannerContext) -> PlannerDecision:  # noqa: ARG002
        decision = self._decisions.pop(0) if self._decisions else PlannerDecision(action="end")
        self.calls += 1
        return decision


class FakeSkills:
    """脚本化 Skill 执行：结果队列耗尽后返回成功空结果。"""

    def __init__(self, results: list[ToolResult] | None = None, exc: Exception | None = None) -> None:
        self._results = list(results or [])
        self._exc = exc
        self.executed: list[SkillCall] = []

    def map_goal_to_skill(self, goal: str) -> SkillCall:
        return SkillCall(skill="boss.extract_jobs", args={"goal": goal}, goal=goal)

    async def execute(self, call: SkillCall) -> ToolResult:
        self.executed.append(call)
        if self._exc is not None:
            raise self._exc
        if self._results:
            return self._results.pop(0)
        return ToolResult(ok=True, data={}, skill=call.skill)


class FakeRuntime:
    """GraphRuntime 协议 Fake；persist/approval/recover 记录调用供断言。"""

    def __init__(self, llm: FakeLLM, skills: FakeSkills, recover_ok: bool = True) -> None:
        self.llm = llm
        self.skills = skills
        self.recover_ok = recover_ok
        self.persisted: list[dict] = []
        self.approvals: list[dict] = []
        self.recovered: list[dict] = []

    async def load_task(self, task_id: str) -> TaskInfo:
        return TaskInfo(task_id=task_id, task_type="proactive_job", thread_id=task_id, conversation_id=None)

    async def list_messages(self, conversation_id: str) -> list[dict]:  # noqa: ARG002
        return [{"message_id": "m1", "text": "历史消息"}]

    async def create_approval(self, context: dict) -> str:
        self.approvals.append(context)
        return "ap-1"

    async def persist(self, state: dict) -> None:
        self.persisted.append(state)

    async def recover_browser(self, error_state: dict) -> bool:
        self.recovered.append(error_state)
        return self.recover_ok


def _initial_state() -> dict:
    return {"task_id": "T1", "task_type": "proactive_job", "thread_id": "T1"}


def _config() -> dict:
    return {"configurable": {"thread_id": f"test-{uuid4().hex[:8]}"}}


async def test_happy_loop_extract_persist_then_end() -> None:
    """快乐循环：提取岗位 -> 落库(needs_persist) -> sync -> planner 结束。"""
    llm = FakeLLM(
        [
            PlannerDecision(action="skill_call", goal="提取岗位", plan=[{"step": 1, "goal": "提取岗位"}]),
            PlannerDecision(action="end", plan=[{"step": 1}]),
        ]
    )
    skills = FakeSkills(
        results=[ToolResult(ok=True, data={"created": 3}, needs_persist=True, skill="boss.extract_jobs")]
    )
    runtime = FakeRuntime(llm, skills)
    graph = build_graph(runtime, checkpointer=InMemorySaver())

    out = await graph.ainvoke(_initial_state(), config=_config())

    assert out["terminal"] == "succeeded"
    assert out["skill_calls"] == [{"skill": "boss.extract_jobs", "args": {"goal": "提取岗位"}, "goal": "提取岗位"}]
    assert out["tool_results"][-1]["data"] == {"created": 3}
    assert len(runtime.persisted) == 1  # needs_persist -> sync 恰好落库一次


async def test_approval_interrupt_and_resume() -> None:
    """敏感操作 -> interrupt 暂停 -> Command(resume) 同 thread 续跑。"""
    llm = FakeLLM(
        [
            # 第一轮：敏感操作未配置 -> 走 approval
            PlannerDecision(action="skill_call", goal="发送打招呼", needs_approval=True, approval_type="send_message"),
            # resume(approve) 后第二轮：真正执行
            PlannerDecision(action="skill_call", goal="发送打招呼"),
            PlannerDecision(action="end"),
        ]
    )
    skills = FakeSkills()
    runtime = FakeRuntime(llm, skills)
    graph = build_graph(runtime, checkpointer=InMemorySaver())
    config = _config()

    # 第一段：执行到 approval 节点触发 interrupt，图暂停返回
    out = await graph.ainvoke(_initial_state(), config=config)
    assert "__interrupt__" in out
    assert runtime.approvals and runtime.approvals[0]["type"] == "send_message"

    # 第二段：Command(resume) 同 thread_id 续跑至终态
    out2 = await graph.ainvoke(Command(resume="approve"), config=config)
    assert out2["terminal"] == "succeeded"
    assert out2["approval_state"]["decision"] == "approve"
    assert len(skills.executed) == 1  # 暂停期间未执行 Skill


async def test_invalid_resume_decision_treated_as_deny() -> None:
    """非法 resume 值按 deny 处理，不中断图（doc 06 §15）。"""
    llm = FakeLLM(
        [
            PlannerDecision(action="skill_call", goal="发送打招呼", needs_approval=True, approval_type="send_message"),
            PlannerDecision(action="end"),
        ]
    )
    runtime = FakeRuntime(llm, FakeSkills())
    graph = build_graph(runtime, checkpointer=InMemorySaver())
    config = _config()
    await graph.ainvoke(_initial_state(), config=config)
    out = await graph.ainvoke(Command(resume="hack"), config=config)
    assert out["approval_state"]["decision"] == "deny"
    assert out["terminal"] == "succeeded"


async def test_dom_change_recover_then_retry_succeeds() -> None:
    """DOM 异常 -> browser_recovery 恢复 -> 重试成功。"""

    class FlakySkills(FakeSkills):
        def __init__(self) -> None:
            super().__init__()
            self.failures = 2

        async def execute(self, call: SkillCall) -> ToolResult:
            self.executed.append(call)  # 失败也计入执行次数（重试断言依据）
            if self.failures > 0:
                self.failures -= 1
                raise RuntimeError("jobList 不存在")  # noqa: EM101
            return ToolResult(ok=True, data={}, skill=call.skill)

    llm = FakeLLM([PlannerDecision(action="skill_call", goal="提取岗位"), PlannerDecision(action="end")])
    skills = FlakySkills()
    runtime = FakeRuntime(llm, skills, recover_ok=True)
    graph = build_graph(runtime, checkpointer=InMemorySaver())

    out = await graph.ainvoke(_initial_state(), config=_config())

    # 失败 2 次 -> error_recovery 恢复 2 次 -> 第 3 次执行成功
    assert out["terminal"] == "succeeded"
    assert len(skills.executed) == 3
    assert len(runtime.recovered) == 2
    assert out["retry_count"] == 0  # 成功后 tool_executor 清零


async def test_recovery_exhausted_ends_failed() -> None:
    """恢复 Retry 耗尽（上限 2）-> terminal=failed（doc 06 §10）。"""
    llm = FakeLLM([PlannerDecision(action="skill_call", goal="提取岗位")])
    skills = FakeSkills(exc=RuntimeError("页面持续异常"))
    runtime = FakeRuntime(llm, skills, recover_ok=True)
    graph = build_graph(runtime, checkpointer=InMemorySaver())

    out = await graph.ainvoke(_initial_state(), config=_config())

    # 恢复上限 2 -> 共执行 3 次（首跑 + 2 重试）后 failed
    assert out["terminal"] == "failed"
    assert len(skills.executed) == 3
    assert out["retry_count"] == 3


async def test_rule_violation_fails_without_retry() -> None:
    """规则违反（DomainGuard 拒绝）不重试、不走 browser_recovery，直接 failed。"""
    llm = FakeLLM([PlannerDecision(action="skill_call", goal="越权操作")])
    skills = FakeSkills(exc=ValueError("DomainGuard 拒绝：目标不在域白名单"))
    runtime = FakeRuntime(llm, skills)
    graph = build_graph(runtime, checkpointer=InMemorySaver())

    out = await graph.ainvoke(_initial_state(), config=_config())

    assert out["terminal"] == "failed"
    assert len(skills.executed) == 1  # 不重试
    assert len(runtime.recovered) == 0  # 不走 browser_recovery
    assert out["error_state"]["kind"] == "rule_violation"
    assert out["error_state"]["unrecoverable"] is True


async def test_unknown_task_type_normalized_to_recovery() -> None:
    """DB 脏 task_type（receive_task 先于 classify）-> 归一为 recovery。"""

    # receive_task 先于 classify 执行，DB 返回的脏值才是 classify 的真实输入
    class DirtyTaskRuntime(FakeRuntime):
        async def load_task(self, task_id: str) -> TaskInfo:
            return TaskInfo(task_id=task_id, task_type="unknown_type", thread_id=task_id)

    llm = FakeLLM([PlannerDecision(action="end")])
    graph = build_graph(DirtyTaskRuntime(llm, FakeSkills()), checkpointer=InMemorySaver())
    state = {**_initial_state(), "task_type": "unknown_type"}
    out = await graph.ainvoke(state, config=_config())
    assert out["task_type"] == "recovery"
