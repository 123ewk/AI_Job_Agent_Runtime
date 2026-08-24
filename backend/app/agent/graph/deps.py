"""Graph 对 Runtime 的依赖契约（doc 06 §5/§14）。

依赖倒置：graph 节点只依赖本文件的 Protocol 与 DTO，不依赖尚未实现的
runtime/ 具体类；runtime/（doc 04）后续实现 GraphRuntime 即可接线。
测试用 FakeRuntime 满足同一协议（duck-typing，无需继承）。
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from app.agent.graph.state import AgentState

# ---------------------------------------------------------------------------
# 错误分类（doc 06 §11：error_recovery 分支依据）
# ---------------------------------------------------------------------------
ERROR_KIND_DOM_CHANGE = "dom_change"
ERROR_KIND_LLM = "llm"
ERROR_KIND_NETWORK = "network"
ERROR_KIND_TIMEOUT = "timeout"
ERROR_KIND_RULE_VIOLATION = "rule_violation"

# 恢复 Retry 上限（doc 06 §10：error_recovery 子图重试 2 次）
MAX_RECOVERY_RETRY = 2

NextAction = Literal["skill_call", "approval", "sync", "end"]


class LLMPlanError(Exception):
    """planner LLM 调用失败（超时/限流/网络），可被 RetryPolicy 瞬时重试。"""


@dataclass(frozen=True, slots=True)
class TaskInfo:
    """receive_task 从 DB 装载的任务元数据（doc 06 §5.1）。

    user_id 供图节点/builder 广播 task.step 时定位用户通道（单用户 V1 固定 1，
    默认值保证 FakeRuntime 等测试构造不受影响）。
    """

    task_id: str
    task_type: str
    thread_id: str
    conversation_id: str | None = None
    user_id: int = 1


@dataclass(frozen=True, slots=True)
class PlannerContext:
    """planner 决策输入：会话历史 + 当前计划 + 最近观察 + Approval 决策。"""

    task_type: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    plan: list[dict[str, Any]] = field(default_factory=list)
    current_step: int = 0
    recent_result: dict[str, Any] | None = None  # 最近一次 tool_result（观察）
    approval_decision: str | None = None  # approve|deny|timeout


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    """planner 输出：下一动作 + 完整计划（doc 06 §5.3）。"""

    action: NextAction
    plan: list[dict[str, Any]] = field(default_factory=list)
    needs_approval: bool = False
    approval_type: str | None = None  # doc 14 七类敏感信息（salary/location/...）
    goal: str | None = None  # skill_call 时的目标描述（供 map_goal_to_skill）


@dataclass(frozen=True, slots=True)
class SkillCall:
    """skill_router 产出：目标映射到的 Skill 与入参（doc 06 §5.4）。"""

    skill: str
    args: dict[str, Any] = field(default_factory=dict)
    goal: str = ""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """tool_executor 观察结果（doc 06 §5.5；对齐 doc 08 SkillResult 契约）。"""

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    error_kind: str | None = None  # 失败时必填：ERROR_KIND_* 之一
    needs_persist: bool = False  # 命中落库 -> 条件边转 sync
    skill: str = ""

    def to_state(self) -> dict[str, Any]:
        """转为可存入 AgentState.tool_results 的 plain dict。"""
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "error_kind": self.error_kind,
            "needs_persist": self.needs_persist,
            "skill": self.skill,
        }


class PlannerLike(Protocol):
    """planner 节点依赖的 LLM 决策接口（实现在 prompts/planner.py）。"""

    async def plan(self, ctx: PlannerContext) -> PlannerDecision: ...


class SkillExecutorLike(Protocol):
    """skill_router / tool_executor 依赖的 Skill 执行接口（tools/router.py）。

    浏览器锁由实现方内部持有（runtime.locks.browser），节点不感知锁细节。
    """

    def map_goal_to_skill(self, goal: str) -> SkillCall: ...

    async def execute(self, call: SkillCall) -> ToolResult: ...


class GraphRuntime(Protocol):
    """graph 节点所需的 Runtime 能力集合（doc 06 §14 接口表）。

    实现方：runtime/workflow_engine.py（doc 04 WorkflowEngine 宿主）。
    """

    async def load_task(self, task_id: str) -> TaskInfo: ...

    async def list_messages(self, conversation_id: str) -> list[dict[str, Any]]: ...

    async def create_approval(self, context: dict[str, Any]) -> str:
        """写 approvals 表并经 WS 推送 approval.required，返回 approval_id。"""
        ...

    async def persist(self, state: "AgentState") -> None:
        """SyncService 落库（doc 13）：消息/状态变更持久化。"""
        ...

    async def recover_browser(self, error_state: dict[str, Any]) -> bool:
        """browser_recovery_agent 恢复尝试（doc 15）；True=已恢复可重试。"""
        ...

    @property
    def llm(self) -> PlannerLike: ...

    @property
    def skills(self) -> SkillExecutorLike: ...
