"""消息模型。

来源（spec 同步系统）：manual（用户手动回复）/ agent（Agent 发送）/ history（页面历史记录）。
external_msg_id 用于跨来源去重，避免同一 Boss 消息重复入库。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_sent", "conversation_id", "sent_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    # 角色：user / agent / hr / system
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 来源：manual / agent / history
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_msg_id: Mapped[str | None] = mapped_column(String(100), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
