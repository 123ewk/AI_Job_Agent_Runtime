"""Workflow 引擎（doc 04 §5/§12）：GraphRuntime 协议的生产实现。

职责单一：宿主 LangGraph 图（build_graph），把协议 7 项能力接到
Repository/Service/Skill，并维护任务生命周期
run -> suspend(Interrupt) -> resume -> terminal；
执行锁贯穿挂起期间（doc 04 §8.1 V1 严格单任务：暂停不释放锁）。

DB 访问模式：每次操作独立短 session（async with session_factory()），
不跨节点持有长事务——图执行可达分钟级，长事务会占死连接池连接，
且 LangGraph 节点重试要求每次 DB 副作用自包含。

测试注入点：_fetch_task/_fetch_messages/_set_task_status/_create_approval_record
四个 DB 边界方法可被子类覆写（与 graph 测试 FakeRuntime 同思路），
run/resume/锁/Interrupt 编排逻辑因此可在无 DB 环境下全覆盖。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.graph.builder import build_graph
from app.agent.graph.deps import PlannerLike, SkillExecutorLike, TaskInfo
from app.agent.graph.state import AgentState
from app.agent.prompts.planner import LangchainPlanner, PlannerLLMConfig
from app.agent.runtime.lock_manager import LockManager
from app.agent.runtime.ws_hub import emit_approval_required, emit_notification, emit_task_updated
from app.core.exceptions import NotFoundError
from app.db.base import get_session_factory
from app.models.message import Message
from app.models.task import Task
from app.repository.message import MessageRepository
from app.repository.task import TaskRepository
from app.schema.enums import ApprovalType, TaskStatus
from app.schema.task import ApprovalResponse
from app.service.approval import ApprovalService
from app.service.task import TaskService

logger = logging.getLogger(__name__)

# planner 上下文消息窗口：DB 取最近 N 条（planner render 侧再截 20 条），
# 避免长会话全量加载占 token 预算（doc 06 §17）
MESSAGE_WINDOW = 50

# emit 时 current_task 缺失的兜底 user_id（正常不应触发；与 api/deps 单用户口径一致）
_FALLBACK_USER_ID = 1

PersistFn = Callable[[AgentState], Awaitable[None]]
RecoverFn = Callable[[dict[str, Any]], Awaitable[bool]]
# llm 延迟解析工厂：run() 首次执行前调用拿 planner（需求②：LLM 校验挪到调用期）
PlannerFactory = Callable[[], Awaitable[PlannerLike]]


class EngineStateError(RuntimeError):
    """引擎生命周期误用（如对未挂起的引擎 resume、锁外创建 Approval）。"""


class PlannerConfigError(RuntimeError):
    """LLM 配置不完整，无法组装 planner（引导用户先配置 Settings）。"""


@dataclass(slots=True)
class _TaskContext:
    """run() 装载的任务执行上下文（挂起期间驻留内存供 resume 使用）。

    单任务锁保证同一时刻至多一个非空 _TaskContext，无并发竞争。
    """

    db_id: int
    user_id: int
    thread_id: str  # LangGraph Checkpoint 线锚点
    task_type: str


class WorkflowEngine:
    """GraphRuntime 实现 + 任务生命周期宿主（doc 04 §5）。

    未接线的可选依赖（skills/persist_fn/recover_fn）按 fail-fast 处理：
    访问即抛带明确指引的异常，由图节点上抛 -> run() 捕获 -> 任务 failed。
    唯一例外 recover_browser：协议语义是"能否恢复"的布尔问答，未接线
    返回 False（不可恢复）让图走既有 failed 分支，不中断节点执行。
    """

    def __init__(
        self,
        llm: PlannerLike | None = None,
        *,
        planner_factory: PlannerFactory | None = None,
        skills: SkillExecutorLike | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        locks: LockManager | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        persist_fn: PersistFn | None = None,
        recover_fn: RecoverFn | None = None,
    ) -> None:
        """构造引擎。

        ``llm`` 与 ``planner_factory`` 二选一：
        - 测试/已就绪时直接传 ``llm``（eager）。
        - 生产经 ``planner_factory`` 惰性解析（需求②），启动不校验 LLM，首个任务
          真正执行前才读配置——配好正常跑，未配弹窗提醒且不执行该任务流程。
        """
        self._llm = llm
        self._planner_factory = planner_factory
        self._skills = skills
        self._persist_fn = persist_fn
        self._recover_fn = recover_fn
        self._locks = locks or LockManager()
        self._session_factory = session_factory or get_session_factory()
        self._current_task: _TaskContext | None = None
        # 图在构造期编译一次：节点闭包捕获 self（同一 runtime 实例），
        # 重复 build 会丢失"已编译图与 runtime 的绑定"语义
        self._graph = build_graph(self, checkpointer=checkpointer)

    # ------------------------------------------------------------------
    # GraphRuntime 协议实现（graph/deps.py，节点闭包经此触达外部世界）
    # ------------------------------------------------------------------
    @property
    def llm(self) -> PlannerLike:
        return self._llm

    @property
    def skills(self) -> SkillExecutorLike:
        if self._skills is None:
            msg = "SkillExecutor 未接线：实现 tools/router.py 后注入（doc 07）"
            raise EngineStateError(msg)
        return self._skills

    async def load_task(self, task_id: str) -> TaskInfo:
        """receive_task 节点回调：DB 任务行 -> 图内任务元数据 DTO。

        thread_id 缺失时回退 task-{id}：Checkpoint 必须有稳定锚点，
        且同任务多次执行（retry）需落同一线才能续跑。
        """
        task = await self._fetch_task(task_id)
        thread = str(task.thread_id) if task.thread_id else f"task-{task.id}"
        if task.thread_id is None:
            logger.warning("Task has no thread_id, fallback anchor", extra={"task_id": task.id})
        return TaskInfo(
            task_id=str(task.id),
            task_type=task.type,
            thread_id=thread,
            conversation_id=str(task.conversation_id) if task.conversation_id else None,
            user_id=task.user_id,
        )

    async def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        """receive_task 节点回调：DB 消息 -> planner 上下文 dict（最近 N 条）。"""
        rows = await self._fetch_messages(int(conversation_id))
        return [{"message_id": str(m.id), "sender": m.role, "text": m.content} for m in rows[-MESSAGE_WINDOW:]]

    async def create_approval(self, context: dict[str, Any]) -> str:
        """approval 节点回调：写 approvals 表 + 20s 定时器，返回 approval_id。

        context 为图内 approval_state：{"type": ..., "context": {...}}。
        type 必须是 doc 14 §5.1 七类敏感信息之一（planner prompt 已约束）；
        非法值快速失败——宁可任务 failed 也不落语义不明的审批记录。
        """
        current = self._current_task
        if current is None:
            msg = "create_approval called outside a running task (engine misuse)"
            raise EngineStateError(msg)
        raw_type = str(context.get("type") or "")
        try:
            approval_type = ApprovalType(raw_type)
        except ValueError as exc:
            msg = f"非法审批类型 '{raw_type}'：须为 doc 14 七类敏感信息之一"
            raise ValueError(msg) from exc
        approval = await self._create_approval_record(
            task_id=current.db_id,
            user_id=current.user_id,
            approval_type=approval_type,
            payload=context.get("context") or {},
        )
        # 写审批记录后推 approval.required：前端弹审批框（expires_at 供倒计时）。
        # 在引擎内发而不依赖 ApprovalService 的原因：审批事务在运行时独立推进，
        # 事件由动作源（引擎）在落库点就近广播，语义与 create_approval 的节点回调绑定。
        await emit_approval_required(
            approval.id,
            current.db_id,
            current.user_id,
            approval.expires_at or "",
        )
        return approval.id

    async def persist(self, state: AgentState) -> None:
        """sync 节点回调：SyncService 落库（doc 13，接线前 fail-fast）。"""
        if self._persist_fn is None:
            msg = "SyncService 未接线：实现 doc 13 后以 persist_fn 注入"
            raise EngineStateError(msg)
        await self._persist_fn(state)

    async def recover_browser(self, error_state: dict[str, Any]) -> bool:
        """error_recovery 节点回调：browser_recovery_agent（doc 15）。

        未接线返回 False = "不可恢复"，图走既有 failed 终态分支；
        接线后返回恢复尝试结果（True = 已恢复可重试）。
        """
        if self._recover_fn is None:
            logger.warning(
                "browser recovery not wired, treating as unrecoverable",
                extra={"error": error_state.get("error")},
            )
            return False
        return await self._recover_fn(error_state)

    # ------------------------------------------------------------------
    # 任务生命周期（doc 04 §5：pickup 由 QueueConsumer 调 run()，此处从 run 起）
    # ------------------------------------------------------------------
    async def run(self, task_id: str) -> dict[str, Any]:
        """执行任务至终态或 Interrupt 挂起。

        Returns:
            图最终 state；含 "__interrupt__" 键表示挂起等待 Approval
            （执行锁保持持有，等待 resume()）。

        Raises:
            NotFoundError: 任务不存在（锁外先失败，不占执行锁）。
            LockTimeoutError: 已有任务在跑（上游应重排队而非死等）。
        """
        task = await self._fetch_task(task_id)
        thread_id = str(task.thread_id) if task.thread_id else f"task-{task.id}"

        # 需求②：LLM 延迟校验——任务真正执行前才解析配置（启动期不因未配降级）。
        # 未配置：弹窗提醒 + 标任务 failed，且不执行该任务的图流程（不占执行锁）。
        if not await self._resolve_llm():
            await self._reject_missing_llm(task.id, task.user_id)
            return {
                "terminal": "failed",
                "error_state": {"node": "planner", "error": "LLM 未配置", "kind": "config"},
            }

        await self._locks.acquire_execution()
        self._current_task = _TaskContext(db_id=task.id, user_id=task.user_id, thread_id=thread_id, task_type=task.type)
        try:
            await self._set_task_status(task.id, TaskStatus.RUNNING)
            await emit_task_updated(
                task.id, task.user_id, {"status": TaskStatus.RUNNING.value, "message": "开始执行"}
            )
            result = await self._graph.ainvoke(
                {"task_id": str(task.id)},
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception:
            await self._abort(task.id)
            raise
        return await self._finish_or_suspend(task.id, result)

    async def resume(self, thread_id: str, decision: str) -> dict[str, Any]:
        """Approval 决策到达后从 Checkpoint 续跑（doc 04 §10.2）。

        前置：run() 处于挂起态（_current_task 非空且 thread 匹配），
        执行锁由 run() 持有未释放——resume 必须经同一引擎实例调用。
        """
        current = self._current_task
        if current is None or current.thread_id != thread_id:
            msg = f"resume on thread {thread_id} rejected: engine not suspended on it"
            raise EngineStateError(msg)
        try:
            await self._set_task_status(current.db_id, TaskStatus.RUNNING)
            await emit_task_updated(
                current.db_id, current.user_id, {"status": TaskStatus.RUNNING.value, "message": "审批续跑"}
            )
            result = await self._graph.ainvoke(
                Command(resume=decision),
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception:
            await self._abort(current.db_id)
            raise
        return await self._finish_or_suspend(current.db_id, result)

    async def resume_by_task(self, task_id: int, decision: str) -> dict[str, Any]:
        """按任务 ID 恢复（Approval 决策入口扩展）。

        审批侧只有 task_id，不便去 DB 反查 thread_id；引擎自身持有挂起态
        （_current_task），据此校验并续跑。V1 单挂起任务：若当前挂起的不是该任务
        则抛 EngineStateError（调用方降级，不抢占别的挂起任务）。
        """
        current = self._current_task
        if current is None or current.db_id != task_id:
            msg = f"resume_by_task({task_id}) rejected: engine not suspended on task {getattr(current, 'db_id', None)}"
            raise EngineStateError(msg)
        return await self.resume(current.thread_id, decision)

    async def _finish_or_suspend(self, task_db_id: int, result: dict[str, Any]) -> dict[str, Any]:
        """收尾分流：挂起（保锁）或终态（写状态 + 释放锁）。"""
        user_id = self._current_task.user_id if self._current_task is not None else _FALLBACK_USER_ID
        if "__interrupt__" in result:
            await self._set_task_status(task_db_id, TaskStatus.WAITING_APPROVAL)
            await emit_task_updated(
                task_db_id, user_id, {"status": TaskStatus.WAITING_APPROVAL.value, "message": "等待审批"}
            )
            return result

        terminal = result.get("terminal")
        final = TaskStatus.SUCCEEDED if terminal == "succeeded" else TaskStatus.FAILED
        error_state = result.get("error_state") or {}
        error_msg = str(error_state.get("error") or "") or None
        await self._set_task_status(task_db_id, final, error_message=error_msg)
        await emit_task_updated(task_db_id, user_id, {"status": final.value, "message": error_msg or final.value})
        self._teardown()
        return result

    async def _abort(self, task_db_id: int) -> None:
        """图执行异常收尾：尽力标 failed + 释放锁，不掩盖原始异常。"""
        user_id = self._current_task.user_id if self._current_task is not None else _FALLBACK_USER_ID
        try:
            await self._set_task_status(task_db_id, TaskStatus.FAILED, error_message="graph execution aborted")
            await emit_task_updated(
                task_db_id, user_id, {"status": TaskStatus.FAILED.value, "message": "graph execution aborted"}
            )
        except Exception:
            # 状态流转非法（如从未进 running）也必须释放锁，吞掉次级异常
            logger.exception("Failed to mark task failed during abort", extra={"task_id": task_db_id})
        finally:
            self._teardown()

    def _teardown(self) -> None:
        """清执行上下文并释放执行锁（幂等）。"""
        self._current_task = None
        self._locks.release_execution()

    # ------------------------------------------------------------------
    # LLM 延迟解析（需求②：启动不校验，调用期才检查配置）
    # ------------------------------------------------------------------
    async def _resolve_llm(self) -> bool:
        """确保 planner 就绪（惰性解析）。

        Returns:
            True = LLM 可用（可直接跑图）；False = 未配置（调用方弹窗且不执行）。
        """
        if self._llm is not None:
            return True
        if self._planner_factory is None:
            msg = "planner 既未注入也未提供工厂（装配缺陷）"
            raise EngineStateError(msg)
        try:
            self._llm = await self._planner_factory()
        except PlannerConfigError:
            # 未配置：不缓存结果，下次 run 会重新检查——用户在设置页配好后，
            # 后续任务无需重启即自动生效（不会带着旧的"缺失"僵住）。
            logger.warning("LLM not configured, deferring task execution")
            return False
        return True

    async def _reject_missing_llm(self, task_id: int, user_id: int) -> None:
        """LLM 未配置：弹窗提醒 + 标任务 failed，且不跑该任务流程。

        刻意不写"graph execution aborted"等误导文案——失败原因就是没配 LLM，
        前端据此引导用户去设置页（notification 弹窗 + task.updated 同时推送）。
        """
        msg = "后端 LLM 未配置：请先在设置页配置 api_key 与 model 后再重试"
        await self._set_task_status(task_id, TaskStatus.FAILED, error_message=msg)
        await emit_notification(user_id, "error", "配置缺失", msg)
        await emit_task_updated(task_id, user_id, {"status": TaskStatus.FAILED.value, "message": msg})
        logger.warning("Task skipped: LLM not configured", extra={"task_id": task_id, "user_id": user_id})

    # ------------------------------------------------------------------
    # DB 边界（短 session；测试覆写点）
    # ------------------------------------------------------------------
    async def _fetch_task(self, task_id: str) -> Task:
        db_id = int(task_id)  # ValueError 上抛：非数字 task_id 属调用方错误
        async with self._session_factory() as session:
            task = await TaskRepository(session).get(db_id)
        if task is None:
            msg = f"Task {task_id} not found"
            raise NotFoundError(msg)
        return task

    async def _fetch_messages(self, conversation_id: int) -> list[Message]:
        async with self._session_factory() as session:
            return await MessageRepository(session).list_by_conversation(conversation_id, limit=MESSAGE_WINDOW)

    async def _set_task_status(
        self,
        task_id: int,
        status: TaskStatus,
        *,
        error_message: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            await TaskService(session).update_status(task_id, status, error_message=error_message)

    async def _create_approval_record(
        self,
        task_id: int,
        user_id: int,
        approval_type: ApprovalType,
        payload: dict[str, Any],
    ) -> ApprovalResponse:
        async with self._session_factory() as session:
            return await ApprovalService(session).create(
                task_id=task_id, user_id=user_id, approval_type=approval_type, context=payload
            )


# ----------------------------------------------------------------------
# planner 装配工厂：Settings(llm) -> LangchainPlanner
# ----------------------------------------------------------------------
async def create_planner_from_settings(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: int,
) -> LangchainPlanner:
    """从用户 Settings.llm 分类组装 planner（api_key 已解密）。

    独立成工厂而非引擎构造逻辑：配置读取属装配期一次性动作，与引擎
    运行期职责分离；未配置完整时抛 PlannerConfigError 由调用方引导用户
    （不静默降级——没有 LLM 的 planner 只会把所有任务导向 failed）。
    """
    from app.service.setting import SettingsService

    async with session_factory() as session:
        current = await SettingsService(session).get_llm_runtime_config(user_id)

    api_key = current.get("api_key")
    model = current.get("model")
    if not api_key or not model:
        msg = f"LLM 未配置（user_id={user_id}）：请先在设置页配置 api_key 与 model"
        raise PlannerConfigError(msg)
    return LangchainPlanner(
        PlannerLLMConfig(
            model=str(model),
            api_key=str(api_key),
            base_url=current.get("base_url"),
            temperature=float(current.get("temperature", 0.7)),
        )
    )
