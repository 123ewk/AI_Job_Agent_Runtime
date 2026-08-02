"""消息 Repository。"""

from __future__ import annotations

import datetime

from sqlalchemy import and_, select

from app.models.message import Message
from app.repository.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    """消息数据访问层。

    消息来源：manual（用户手动发）/ agent（Agent 自动发）/ history（同步拉取）。
    外部消息去重键：external_msg_id。
    """

    model = Message

    async def list_by_conversation(
        self,
        conversation_id: int,
        limit: int = 100,
        after_sent_at: datetime.datetime | None = None,
    ) -> list[Message]:
        """按会话列出消息，按时间正序（聊天窗口展示用）。

        after_sent_at 可选游标增量拉取。
        """
        clauses: list = [Message.conversation_id == conversation_id]
        if after_sent_at is not None:
            clauses.append(Message.sent_at > after_sent_at)
        result = await self.session.execute(
            select(Message)
            .where(and_(*clauses))
            .order_by(Message.sent_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_external_id(self, external_msg_id: str) -> Message | None:
        """按外部消息 ID 定位（同步去重用）。"""
        result = await self.session.execute(
            select(Message).where(Message.external_msg_id == external_msg_id)
        )
        return result.scalar_one_or_none()
