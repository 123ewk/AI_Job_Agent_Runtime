"""审批业务服务。

负责 Approval 的创建、决策、超时自动恢复。
Approval 是 Agent 执行中的人工确认中断点，属 Runtime 层。

跨域协作：
- 与 Agent Runtime 协作：触发 Interrupt，恢复执行
- 与 TaskService 协作：waiting_approval 状态流转
- 与 WebSocket 协作：推送 approval.required 事件
- 与定时器协作：20s 超时自动注入 timeout decision
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval as ApprovalModel
from app.models.approval import ApprovalStatus
from app.models.approval import ApprovalType as ModelApprovalType
from app.repository.approval import ApprovalRepository
from app.schema.enums import ApprovalType
from app.schema.task import ApprovalResponse
from app.service.base import BaseService, transactional

# 存储活跃的定时器任务引用，防止 asyncio.create_task 创建的任务被 GC
# weakref 方案更优，但模块级集合对于生命周期短的任务已足够
_active_timers: set[asyncio.Task[Any]] = set()


class ApprovalStateError(ValueError):
    """Approval 状态非法异常。"""


class ApprovalService(BaseService):
    """审批业务服务。

    职责：
    - 创建 Approval（带 20s 超时）
    - 处理用户决策（approve/deny）
    - 超时自动决策（timeout）
    - 并发安全：同一任务同时只能一个 pending Approval
    - 乐观锁防止用户响应与定时器竞争
    - 恢复任务执行（reload Checkpoint + resume）
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)
        self.approval_repo = ApprovalRepository(db)

    def _to_response(self, approval: ApprovalModel) -> ApprovalResponse:
        """ORM Model 转 DTO。

        实现 Model -> DTO 转换，确保 ORM 字段不直接泄漏到 API。
        """
        return ApprovalResponse(
            id=approval.id,
            task_id=approval.task_id,
            user_id=approval.user_id,
            type=ModelApprovalType(approval.type),
            payload=approval.payload,
            status=ApprovalStatus(approval.status),
            expires_at=approval.expires_at.isoformat() if approval.expires_at else None,
            decided_at=approval.decided_at.isoformat() if approval.decided_at else None,
            created_at=approval.created_at.isoformat() if approval.created_at else "",
        )

    @transactional
    async def create(
        self,
        task_id: int,
        user_id: int,
        approval_type: ApprovalType,
        context: dict[str, Any],
        expires_seconds: int = 20,
    ) -> ApprovalResponse:
        """创建 Approval 并中断任务。

        1. 检查是否已有 pending Approval（防重复创建）
        2. 写入 approvals 表（status=pending）
        3. 触发 LangGraph Interrupt，写 Checkpoint
        4. Task 状态 -> waiting_approval
        5. 推送 WS approval.required 事件
        6. 启动超时定时器

        Args:
            task_id: 关联任务 ID
            user_id: 关联用户 ID
            approval_type: 审批类型（salary/location/...）
            context: 展示给用户的上下文（消息、预览、可选操作）
            expires_seconds: 超时秒数（默认 20s）

        Raises:
            ApprovalStateError: 任务已有 pending Approval
        """
        # 1. 并发检查：同一任务只能有一个 pending Approval
        existing_pending = await self.approval_repo.get_latest_pending_by_task(task_id)
        if existing_pending is not None:
            msg = f"Task {task_id} already has a pending approval (id: {existing_pending.id})"
            raise ApprovalStateError(msg)

        # 2. 创建 Approval 记录
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_seconds)
        approval = await self.approval_repo.create({
            "task_id": task_id,
            "user_id": user_id,
            "type": approval_type.value,
            "payload": context,
            "status": ApprovalStatus.PENDING.value,
            "expires_at": expires_at,
        })

        self.log_with_context(
            20,  # INFO
            "approval_created",
            approval_id=approval.id,
            task_id=task_id,
            user_id=user_id,
            approval_type=approval_type.value,
            expires_at=expires_at.isoformat(),
        )

        # 3. TODO: 触发 LangGraph Interrupt，写 Checkpoint

        # 4. TODO: Task 状态 -> waiting_approval（需 TaskService 注入依赖）

        # 5. TODO: WebSocket 推送 approval.required 事件

        # 6. 启动超时定时器（后台异步执行，不阻塞当前事务）
        # 注意：在事务内部启动定时器可能导致超时触发时 Approval 还未提交
        # 实际生产环境建议使用事务 commit 事件回调，或使用消息队列
        self._start_timeout_timer(approval.id, expires_seconds)

        return self._to_response(approval)

    @transactional
    async def approve(self, approval_id: int, user_id: int, user_note: str | None = None) -> ApprovalResponse:
        """用户确认操作。

        乐观锁校验：只有 status=pending 时才可变更。
        变更后 reload Checkpoint，注入 approved decision，恢复任务执行。

        Raises:
            ValueError: Approval 不存在或不属于该用户
            ApprovalStateError: Approval 状态不是 pending，无法决策
        """
        # 乐观锁：使用 get_for_update 行锁 + 状态校验
        approval = await self.approval_repo.get_for_update(approval_id)
        if approval is None:
            msg = f"Approval {approval_id} not found"
            raise ValueError(msg)
        if approval.user_id != user_id:
            msg = f"Approval {approval_id} does not belong to user {user_id}"
            raise ValueError(msg)

        current_status = ApprovalStatus(approval.status)
        if current_status != ApprovalStatus.PENDING:
            # 已被决策（用户或超时），静默返回
            self.log_with_context(
                20,
                "approval_already_decided",
                approval_id=approval_id,
                current_status=current_status.value,
            )
            return self._to_response(approval)

        # 更新状态为 approved
        now = datetime.now(UTC)
        approval.status = ApprovalStatus.APPROVED.value  # type: ignore[attr-defined]
        approval.decision = "approve"  # type: ignore[attr-defined]
        approval.decided_at = now  # type: ignore[attr-defined]

        self.log_with_context(
            20,
            "approval_approved",
            approval_id=approval_id,
            task_id=approval.task_id,
        )

        # 注入 user_note 到 payload（可选）
        if user_note is not None:
            approval.payload = {**approval.payload, "user_note": user_note}  # type: ignore[arg-type]

        # 恢复任务执行
        await self._resume_task(approval.task_id, approval_id, "approve")

        return self._to_response(approval)

    @transactional
    async def deny(self, approval_id: int, user_id: int, reason: str | None = None) -> ApprovalResponse:
        """用户拒绝操作。

        注入 denied decision，任务根据节点逻辑可能终止或走替代分支。

        Raises:
            ValueError: Approval 不存在或不属于该用户
            ApprovalStateError: Approval 状态不是 pending，无法决策
        """
        # 乐观锁：行锁 + 状态校验
        approval = await self.approval_repo.get_for_update(approval_id)
        if approval is None:
            msg = f"Approval {approval_id} not found"
            raise ValueError(msg)
        if approval.user_id != user_id:
            msg = f"Approval {approval_id} does not belong to user {user_id}"
            raise ValueError(msg)

        current_status = ApprovalStatus(approval.status)
        if current_status != ApprovalStatus.PENDING:
            self.log_with_context(
                20,
                "approval_already_decided",
                approval_id=approval_id,
                current_status=current_status.value,
            )
            return self._to_response(approval)

        # 更新状态为 denied
        now = datetime.now(UTC)
        approval.status = ApprovalStatus.DENIED.value  # type: ignore[attr-defined]
        approval.decision = "deny"  # type: ignore[attr-defined]
        approval.decided_at = now  # type: ignore[attr-defined]

        self.log_with_context(
            20,
            "approval_denied",
            approval_id=approval_id,
            task_id=approval.task_id,
        )

        # 注入 reason 到 payload（可选）
        if reason is not None:
            approval.payload = {**approval.payload, "deny_reason": reason}  # type: ignore[arg-type]

        # 恢复任务执行
        await self._resume_task(approval.task_id, approval_id, "deny")

        return self._to_response(approval)

    @transactional
    async def handle_timeout(self, approval_id: int) -> ApprovalResponse | None:
        """处理超时。

        定时器回调，注入 timeout decision。
        若用户已操作，乐观锁冲突则静默跳过（只生效一次）。

        Returns:
            更新后的 Approval，若已被处理则返回 None
        """
        # 乐观锁：行锁 + 状态校验
        approval = await self.approval_repo.get_for_update(approval_id)
        if approval is None:
            self.log_with_context(
                10,  # DEBUG
                "approval_timeout_not_found",
                approval_id=approval_id,
            )
            return None

        current_status = ApprovalStatus(approval.status)
        if current_status != ApprovalStatus.PENDING:
            # 用户已操作，静默跳过
            self.log_with_context(
                20,
                "approval_timeout_skipped",
                approval_id=approval_id,
                current_status=current_status.value,
            )
            return None

        # 更新状态为 timed_out
        now = datetime.now(UTC)
        approval.status = ApprovalStatus.TIMED_OUT.value  # type: ignore[attr-defined]
        approval.decision = "timeout"  # type: ignore[attr-defined]
        approval.decided_at = now  # type: ignore[attr-defined]

        self.log_with_context(
            20,
            "approval_timed_out",
            approval_id=approval_id,
            task_id=approval.task_id,
        )

        # 恢复任务执行（timeout 分支）
        await self._resume_task(approval.task_id, approval_id, "timeout")

        return self._to_response(approval)

    async def get_pending_by_task(self, task_id: int) -> ApprovalResponse | None:
        """获取任务当前待处理的 Approval。"""
        approval = await self.approval_repo.get_latest_pending_by_task(task_id)
        if approval is None:
            return None
        return self._to_response(approval)

    async def list_by_task(self, task_id: int) -> list[ApprovalResponse]:
        """列出任务的所有 Approval 历史。"""
        approvals = await self.approval_repo.list_by_task(task_id)
        return [self._to_response(a) for a in approvals]

    def _start_timeout_timer(self, approval_id: int, expires_seconds: int) -> None:
        """启动超时定时器。

        使用 asyncio.create_task 在后台运行定时器。
        注意：定时器与用户响应可能并发，靠 DB 行锁 + 状态校验保证只生效一次。

        设计原理：
        1. asyncio.create_task 创建后台任务，不阻塞当前协程
        2. await asyncio.sleep(expires_seconds) 等待超时
        3. handle_timeout 使用行锁保证只生效一次
        4. 即使定时器与用户操作并发，行锁保证只有一方成功更新
        """
        async def _timeout_task() -> None:
            try:
                await asyncio.sleep(expires_seconds)
                await self.handle_timeout(approval_id)
            except asyncio.CancelledError:
                self.log_with_context(
                    10,
                    "approval_timer_cancelled",
                    approval_id=approval_id,
                )
            except Exception:
                self.log_with_context(
                    40,  # ERROR
                    "approval_timer_error",
                    approval_id=approval_id,
                    exc_info=True,
                )

        # 启动后台任务并存储引用，防止被 GC
        timer_task = asyncio.create_task(_timeout_task(), name=f"approval_timer_{approval_id}")
        _active_timers.add(timer_task)
        # 任务完成后自动从集合中移除（避免内存泄漏）
        timer_task.add_done_callback(_active_timers.discard)

        self.log_with_context(
            10,
            "approval_timer_started",
            approval_id=approval_id,
            expires_seconds=expires_seconds,
        )

    async def _resume_task(self, task_id: int, approval_id: int, decision: str) -> None:
        """恢复任务执行。

        1. 获取 task_id 与 thread_id
        2. WorkflowEngine.reload_checkpoint(thread_id)
        3. 注入 decision 到 State
        4. Task 状态 -> running
        5. 推送 WS task.updated 事件

        注意：此方法在事务内部调用，@transactional 保证状态变更原子性。
        TODO: 待 WorkflowEngine 实现后补充完整逻辑
        """
        self.log_with_context(
            20,
            "task_resume_requested",
            task_id=task_id,
            approval_id=approval_id,
            decision=decision,
        )

        # TODO: 注入 WorkflowEngine 并 reload checkpoint
        # TODO: 注入 decision 到 LangGraph State
        # TODO: 调用 TaskService.update_status 改为 running

        # 临时占位：日志记录即可
