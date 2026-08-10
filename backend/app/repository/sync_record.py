"""同步记录 Repository。"""

from __future__ import annotations

from sqlalchemy import and_, desc, select

from app.models.sync_record import SyncRecord
from app.repository.base import BaseRepository


class SyncRecordRepository(BaseRepository[SyncRecord]):
    """同步记录数据访问层。

    模式：initial（初次）/ manual（手动）/ incremental（增量）。
    状态：running / completed / failed。
    """

    model = SyncRecord

    async def list_by_user(
        self,
        user_id: int,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[SyncRecord]:
        """按用户列出同步记录。"""
        filters = {"user_id": user_id}
        if status is not None:
            filters["status"] = status
        return await self.list_by_filter(filters, limit=limit)

    async def list_by_conversation(self, conversation_id: int) -> list[SyncRecord]:
        """按会话列出同步记录。"""
        return await self.list_by_filter({"conversation_id": conversation_id})

    async def get_latest_by_user(self, user_id: int) -> SyncRecord | None:
        """获取用户最近的同步记录。"""
        result = await self.session.execute(
            select(SyncRecord)
            .where(SyncRecord.user_id == user_id)
            .order_by(desc(SyncRecord.started_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_running_by_user(self, user_id: int) -> SyncRecord | None:
        """获取用户正在进行中的同步（避免重复触发）。"""
        result = await self.session.execute(
            select(SyncRecord).where(
                and_(
                    SyncRecord.user_id == user_id,
                    SyncRecord.status == "running",
                )
            )
        )
        return result.scalar_one_or_none()

    async def mark_completed(
        self,
        record_id: int,
        messages_synced: int,
    ) -> SyncRecord | None:
        """标记同步完成。"""
        return await self.update(
            record_id,
            {
                "status": "completed",
                "messages_synced": messages_synced,
            },
        )

    async def mark_failed(self, record_id: int, error: str) -> SyncRecord | None:
        """标记同步失败。"""
        return await self.update(
            record_id,
            {
                "status": "failed",
                "error": error,
            },
        )
