"""会话 Repository。"""

from __future__ import annotations

from sqlalchemy import and_, select

from app.models.conversation import Conversation
from app.repository.base import BaseRepository


class ConversationRepository(BaseRepository[Conversation]):
    """会话数据访问层。

    Conversation = 与一个 HR 的聊天线程。
    与 Job 1:1 绑定（1 岗位 = 1 条聊天线）。
    """

    model = Conversation

    async def get_by_uuid(self, uuid: str) -> Conversation | None:
        """按业务 UUID 定位（前端/Agent 引用用）。"""
        result = await self.session.execute(
            select(Conversation).where(Conversation.uuid == uuid)
        )
        return result.scalar_one_or_none()

    async def get_by_job_id(self, job_id: int) -> Conversation | None:
        """按岗位 ID 定位（1 岗位 1 会话保证）。"""
        result = await self.session.execute(
            select(Conversation).where(Conversation.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def get_by_platform_external(
        self,
        platform: str,
        external_id: str,
    ) -> Conversation | None:
        """按平台外部 ID 定位（同步去重用）。"""
        result = await self.session.execute(
            select(Conversation).where(
                and_(
                    Conversation.platform == platform,
                    Conversation.external_id == external_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_active(self, user_id: int, limit: int = 50) -> list[Conversation]:
        """列出用户当前活跃会话（前端聊天列表页用）。"""
        return await self.list_by_filter(
            {"user_id": user_id, "status": "active"},
            order_by="updated_at",
            limit=limit,
        )

    async def count_active(self, user_id: int) -> int:
        """统计用户活跃会话数（并发限流检查用）。

        count_by_filter 只发 COUNT 聚合，比 list_active 取全量再 len 更省。
        """
        return await self.count_by_filter({"user_id": user_id, "status": "active"})
