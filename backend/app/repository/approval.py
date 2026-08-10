"""人工确认 Repository。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, desc, select

from app.models.approval import Approval, ApprovalStatus
from app.repository.base import BaseRepository


class ApprovalRepository(BaseRepository[Approval]):
    """人工确认数据访问层。

    状态：pending / approved / denied / timed_out。
    20 秒超时机制对应 pending + expires_at 过滤。
    """

    model = Approval

    async def list_by_task(self, task_id: int) -> list[Approval]:
        """按任务列出所有确认请求。"""
        return await self.list_by_filter({"task_id": task_id})

    async def list_by_user_status(
        self,
        user_id: int,
        status: ApprovalStatus | str,
        limit: int | None = None,
    ) -> list[Approval]:
        """按用户 + 状态列出确认请求。"""
        return await self.list_by_filter(
            {"user_id": user_id, "status": str(status)},
            limit=limit,
        )

    async def get_pending_expired(self, before: datetime, limit: int = 100) -> list[Approval]:
        """获取已超时的待处理确认（定时任务扫描用）。

        利用部分索引 ix_approvals_expires_pending 加速查询。
        """
        result = await self.session.execute(
            select(Approval).where(
                and_(
                    Approval.status == ApprovalStatus.PENDING.value,
                    Approval.expires_at <= before,
                )
            )
            .order_by(Approval.expires_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_latest_pending_by_task(self, task_id: int) -> Approval | None:
        """获取任务最新的待处理确认。"""
        result = await self.session.execute(
            select(Approval)
            .where(
                and_(
                    Approval.task_id == task_id,
                    Approval.status == ApprovalStatus.PENDING.value,
                )
            )
            .order_by(desc(Approval.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_by_user_status(
        self,
        user_id: int,
        status: ApprovalStatus | str,
    ) -> int:
        """统计用户指定状态的确认数量。"""
        result = await self.session.execute(
            select(Approval.id).where(
                and_(
                    Approval.user_id == user_id,
                    Approval.status == str(status),
                )
            )
        )
        return len(result.scalars().all())
