"""任务业务服务。

负责 Task 的生命周期管理、状态流转、队列操作、Cancel 控制。
Task 是 Agent 执行的最小单元，一次只执行一个。

跨域协作：
- 与 Queue 系统协作：任务入队、ACK、死信
- 与 Agent Runtime 协作：加载 Checkpoint、触发执行、Interrupt 恢复
- 与 Approval 系统协作：waiting_approval 状态管理与超时
- 与 WebSocket 协作：任务状态变更实时推送
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.task import Task as TaskModel
from app.repository.task import TaskRepository
from app.repository.task_checkpoint_index import TaskCheckpointIndexRepository
from app.schema.enums import TaskPriority, TaskStatus, TaskType
from app.schema.task import TaskCreate, TaskFilterParams, TaskResponse
from app.service.base import BaseService, transactional

# 延迟导入，避免循环依赖（service -> infra -> service）
# QueueClient 首次访问时才实际 import
_QueueClient = None
_QueueMessage = None


def _get_queue_classes() -> tuple[Any, Any]:
    """懒加载 Queue 相关类，避免循环 import。

    service -> infra -> service 会形成循环依赖链：
    TaskService -> QueueClient -> TaskService（幂等性检查）
    因此采用首次调用时才实际 import 的方式打破循环。
    """
    global _QueueClient, _QueueMessage  # noqa: PLW0603
    if _QueueClient is None:
        from app.infra.queue import QueueClient as QC
        from app.infra.queue import QueueMessage as QM

        _QueueClient = QC
        _QueueMessage = QM
    return _QueueClient, _QueueMessage


class TaskStateError(ConflictError):
    """任务状态流转非法异常（继承 ConflictError → 409）。

    改为继承 ConflictError 后，状态机违规经全局 handler 返回 409 而非 500。
    """


class TaskService(BaseService):
    """任务业务服务。

    职责：
    - Task CRUD 与状态流转校验
    - 任务入队与优先级分配
    - 取消任务（含运行中终止）
    - 任务重试（受 max_retries=2 约束）
    - 任务状态变更的 WS 推送
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)
        self.task_repo = TaskRepository(db)
        self.checkpoint_repo = TaskCheckpointIndexRepository(db)

    def _to_response(self, task: TaskModel) -> TaskResponse:
        """ORM Model 转 DTO。

        实现 Model -> DTO 转换，确保 ORM 字段不直接泄漏到 API。
        progress 由 payload["progress"] 派生（update_status 写入），
        并收敛到 0-100，与 TaskResponse.progress 的 Pydantic 约束一致。
        """
        raw_progress = task.payload.get("progress", 0) if isinstance(task.payload, dict) else 0
        progress = 0 if not isinstance(raw_progress, int) else max(0, min(100, raw_progress))
        return TaskResponse(
            id=task.id,
            user_id=task.user_id,
            type=TaskType(task.type),
            conversation_id=task.conversation_id,
            job_id=task.job_id,
            status=TaskStatus(task.status),
            priority=TaskPriority(task.priority),
            retry_count=task.retry_count,
            max_retries=task.max_retries,
            progress=progress,
            error_message=task.error,
            result=task.result,
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
            created_at=task.created_at.isoformat() if task.created_at else "",
        )

    @transactional
    async def create(self, user_id: int, data: TaskCreate) -> TaskResponse:
        """创建任务并入队。

        自动分配优先级：
        - approval_resume: P0（最高）
        - hr_reply: P1
        - user_initiated: P2
        - background_scan / proactive_job: P3（最低）

        状态流转：pending。

        设计说明：
        1. 事务内创建 DB 记录
        2. thread_id：调用方指定优先（延续上下文），否则新建 UUID（LangGraph Checkpoint 锚点）
        3. 队列入队 Redis Stream（按优先级分流）
        4. 返回 DTO
        """
        # 自动分配优先级
        priority = self._get_priority_by_type(data.type) if data.priority is None else data.priority

        # 优先使用调用方指定 thread_id（延续已有上下文，doc 03: task.thread_id = conversation.thread_id），
        # 未指定则新建。非法 UUID 立即 400，避免脏数据入库。
        if data.thread_id is not None:
            try:
                thread_id: UUID = UUID(data.thread_id)
            except ValueError as exc:
                # 输入非法时先赋给变量再抛异常，避免 f-string 直接进异常（ruff EM102）
                msg = f"无效的 thread_id: {data.thread_id}"
                raise BadRequestError(msg) from exc
        else:
            thread_id = uuid4()

        # 创建 Task Model
        task = await self.task_repo.create(
            {
                "user_id": user_id,
                "type": data.type.value,
                "status": TaskStatus.PENDING.value,
                "thread_id": thread_id,
                "conversation_id": data.conversation_id,
                "job_id": data.job_id,
                "priority": priority.value,
                "payload": data.params,
            }
        )

        self.log_with_context(
            20,  # INFO
            "task_created",
            task_id=task.id,
            user_id=user_id,
            task_type=data.type.value,
            priority=priority.value,
            thread_id=str(thread_id),
        )

        # ---------------- 入队 Redis Stream
        QueueClient, QueueMessage = _get_queue_classes()
        queue = QueueClient()
        message = QueueMessage(
            task_id=str(task.id),
            task_type=data.type.value,
            thread_id=thread_id,
            # 队列消息的 task_id/conversation_id 统一为「DB int 主键序列化串」，
            # 避免消费端 UUID() 解析 int PK（"123"）时 ValueError。
            conversation_id=str(data.conversation_id) if data.conversation_id else None,
            priority=priority.value,
            payload=data.params or {},
        )
        await queue.enqueue(message)

        return self._to_response(task)

    async def get_by_id(self, user_id: int, task_id: int) -> TaskResponse:
        """获取任务详情。"""
        task = await self.task_repo.get(task_id)
        if task is None or task.user_id != user_id:
            msg = f"Task {task_id} not found"
            raise NotFoundError(msg)
        return self._to_response(task)

    async def list(
        self,
        user_id: int,
        filters: TaskFilterParams,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[TaskResponse], int]:
        """按条件筛选任务列表，返回 (items, total_count)。

        契约与 PaginatedResponse 对齐：路由解包元组、传 page/page_size。
        与 JobService.list 保持同一模式，避免 N+1 分页计数。
        """
        filter_dict: dict[str, Any] = {"user_id": user_id}
        if filters.status is not None:
            filter_dict["status"] = filters.status.value
        if filters.type is not None:
            filter_dict["type"] = filters.type.value
        if filters.conversation_id is not None:
            filter_dict["conversation_id"] = filters.conversation_id
        if filters.job_id is not None:
            filter_dict["job_id"] = filters.job_id

        tasks, total = await self.task_repo.list_by_filter_with_count(
            filter_dict,
            page=page,
            page_size=page_size,
        )
        return [self._to_response(t) for t in tasks], total

    @transactional
    async def cancel(self, user_id: int, task_id: int) -> TaskResponse:
        """取消任务。

        - pending: 直接标记 canceled，从队列移除
        - running: 标记 cancel_requested，Runtime 下一个节点检查后终止
        - waiting_approval: 标记 canceled，拒绝 pending approval
        - 终态: 无操作

        设计说明：
        - 使用行锁防止并发状态变更竞争
        - 终态任务不允许取消
        - running 状态不强制终止，由 Runtime 下一个检查点优雅退出
        """
        # 行锁：防止并发状态变更
        task = await self.task_repo.get_for_update(task_id)
        if task is None or task.user_id != user_id:
            msg = f"Task {task_id} not found"
            raise NotFoundError(msg)

        current_status = TaskStatus(task.status)

        # 终态任务不允许重复取消
        if current_status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELED}:
            self.log_with_context(
                20,
                "task_cancel_skip_terminal",
                task_id=task_id,
                current_status=current_status.value,
            )
            return self._to_response(task)

        # 更新状态
        task.status = TaskStatus.CANCELED.value  # type: ignore[attr-defined]
        task.completed_at = datetime.now(UTC)  # type: ignore[attr-defined]

        self.log_with_context(
            20,
            "task_canceled",
            task_id=task_id,
            previous_status=current_status.value,
        )

        # TODO: 从队列移除（如果 pending）
        # TODO: 拒绝关联的 pending approval（如果 waiting_approval）

        return self._to_response(task)

    @transactional
    async def retry(self, user_id: int, task_id: int) -> TaskResponse:
        """重试失败任务。

        仅限 failed 状态，retry_count < max_retries（默认 2）。
        创建新 task 继承原 task 的上下文（同 thread_id 以复用 Checkpoint）。

        设计说明：
        - 不是更新原任务，而是创建新任务（保证审计日志完整）
        - 复用 thread_id 以复用之前的 Checkpoint，避免从头开始执行
        - retry_count 继承自原任务 + 1
        """
        original_task = await self.task_repo.get(task_id)
        if original_task is None or original_task.user_id != user_id:
            msg = f"Task {task_id} not found"
            raise NotFoundError(msg)

        current_status = TaskStatus(original_task.status)
        if current_status != TaskStatus.FAILED:
            retry_msg = f"Can only retry failed tasks, current: {current_status.value}"
            raise TaskStateError(retry_msg)

        if original_task.retry_count >= original_task.max_retries:
            max_retry_msg = (
                f"Task {task_id} reached max retries "
                f"({original_task.retry_count}/{original_task.max_retries})"
            )
            raise TaskStateError(max_retry_msg)

        # 创建重试任务，复用原 thread_id
        priority = TaskPriority(original_task.priority)
        retried_task = await self.task_repo.create(
            {
                "user_id": user_id,
                "type": original_task.type,
                "status": TaskStatus.PENDING.value,
                "thread_id": original_task.thread_id,  # 复用 Checkpoint 锚点
                "conversation_id": original_task.conversation_id,
                "job_id": original_task.job_id,
                "priority": priority.value,
                "payload": original_task.payload,
                "retry_count": original_task.retry_count + 1,
                "max_retries": original_task.max_retries,
            }
        )

        self.log_with_context(
            20,
            "task_retried",
            original_task_id=task_id,
            new_task_id=retried_task.id,
            retry_count=retried_task.retry_count,
            max_retries=retried_task.max_retries,
        )

        # TODO: 入队 Redis Stream

        return self._to_response(retried_task)

    @transactional
    async def update_status(
        self,
        task_id: int,
        new_status: TaskStatus,
        *,
        progress: int | None = None,
        error_message: str | None = None,
    ) -> TaskResponse:
        """更新任务状态。

        由 Agent Runtime 回调，仅允许合法状态流转：
        pending -> running -> waiting_approval -> recovering -> succeeded/failed/canceled

        状态变更时触发 WS 推送（待 WebSocket 实现后补充）。

        设计说明：
        - 使用行锁防止并发状态变更竞争
        - 状态机校验：非法流转直接拒绝
        - 自动设置 started_at/completed_at 时间戳
        - 更新失败时事务回滚，保证状态一致性
        """
        task = await self.task_repo.get_for_update(task_id)
        if task is None:
            msg = f"Task {task_id} not found"
            raise NotFoundError(msg)

        current_status = TaskStatus(task.status)

        # 状态机校验
        if not self._validate_status_transition(current_status, new_status):
            transition_msg = f"Invalid status transition: {current_status.value} -> {new_status.value}"
            raise TaskStateError(transition_msg)

        # 更新状态
        task.status = new_status.value  # type: ignore[attr-defined]

        # 自动设置时间戳
        if new_status == TaskStatus.RUNNING and task.started_at is None:
            task.started_at = datetime.now(UTC)  # type: ignore[attr-defined]

        if new_status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELED}:
            task.completed_at = datetime.now(UTC)  # type: ignore[attr-defined]

        # 更新错误信息
        if error_message is not None:
            task.error = error_message  # type: ignore[attr-defined]

        # 进度写回 payload，供 _to_response 派生 progress 字段
        if progress is not None:
            payload = dict(task.payload or {})
            payload["progress"] = progress
            task.payload = payload  # type: ignore[assignment]

        self.log_with_context(
            20,
            "task_status_updated",
            task_id=task_id,
            from_status=current_status.value,
            to_status=new_status.value,
        )

        # TODO: WebSocket 推送状态变更事件

        return self._to_response(task)

    async def get_running_task(self, user_id: int) -> TaskResponse | None:
        """获取用户当前运行中的任务。

        单任务保证：同一用户同时只允许一个 running 状态任务。
        调度器在 pick 新任务前必须检查此方法。
        """
        tasks = await self.task_repo.list_by_filter(
            {"user_id": user_id, "status": TaskStatus.RUNNING.value},
            limit=1,
        )
        if not tasks:
            return None
        return self._to_response(tasks[0])

    async def get_pending_tasks_count(self, user_id: int) -> int:
        """获取待执行任务数。"""
        return await self.task_repo.count_by_filter(
            {"user_id": user_id, "status": TaskStatus.PENDING.value}
        )

    @transactional
    async def register_checkpoint(self, task_id: int, thread_id: str, checkpoint_id: str) -> None:
        """注册 Checkpoint 索引。

        建立 task_id <-> thread_id <-> checkpoint_id 的映射，便于：
        1. 按任务查询检查点历史
        2. 崩溃恢复时定位最新检查点
        3. 终态后清理 Checkpoint
        """
        # TODO: 实现 TaskCheckpointIndexRepository
        # await self.checkpoint_repo.create({
        #     "task_id": task_id,
        #     "thread_id": thread_id,
        #     "checkpoint_id": checkpoint_id,
        #     "status": "active",
        # })
        self.log_with_context(
            20,
            "checkpoint_registered",
            task_id=task_id,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
        )

    def _get_priority_by_type(self, task_type: TaskType) -> TaskPriority:
        """根据任务类型分配队列优先级。

        P0: approval_resume（中断恢复最高优先）
        P1: hr_reply（HR 消息回复需要及时）
        P2: user_initiated（用户主动触发）
        P3: background_scan / proactive_job（后台低优先级）
        """
        priority_map = {
            TaskType.APPROVAL_RESUME: TaskPriority.P0,
            TaskType.HR_REPLY: TaskPriority.P1,
            TaskType.USER_INITIATED: TaskPriority.P2,
            TaskType.BACKGROUND_SCAN: TaskPriority.P3,
            TaskType.PROACTIVE_JOB: TaskPriority.P3,
            TaskType.PROACTIVE_CHAT: TaskPriority.P2,
            TaskType.SYNC: TaskPriority.P1,
            TaskType.RECOVERY: TaskPriority.P0,
        }
        return priority_map.get(task_type, TaskPriority.P3)

    def _validate_status_transition(self, current: TaskStatus, new: TaskStatus) -> bool:
        """校验状态流转合法性。

        合法流转：
        pending -> running / canceled
        running -> waiting_approval / succeeded / failed / canceled / recovering
        waiting_approval -> running (resume) / canceled
        recovering -> running / failed
        succeeded / failed / canceled -> （终态，不可变）

        设计原理：
        - 状态机定义在 Service 层，是业务规则的一部分
        - 任何状态变更必须经过此校验（包括 API 调用、Runtime 回调、超时触发）
        - DB 层 CHECK 约束只校验枚举值范围，不校验流转顺序
        """
        valid_transitions: dict[TaskStatus, set[TaskStatus]] = {
            TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELED},
            TaskStatus.RUNNING: {
                TaskStatus.WAITING_APPROVAL,
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.CANCELED,
                TaskStatus.RECOVERING,
            },
            TaskStatus.WAITING_APPROVAL: {TaskStatus.RUNNING, TaskStatus.CANCELED},
            TaskStatus.RECOVERING: {TaskStatus.RUNNING, TaskStatus.FAILED},
            TaskStatus.SUCCEEDED: set(),
            TaskStatus.FAILED: set(),
            TaskStatus.CANCELED: set(),
        }
        return new in valid_transitions.get(current, set())
