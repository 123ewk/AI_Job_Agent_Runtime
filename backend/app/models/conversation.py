"""会话模型：对应一个平台 HR 聊天窗口。

Conversation ID 规则（spec P0）：Boss ID + 内部 UUID。
external_id 存平台侧 ID，uuid 为内部生成的 UUID。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID as UUID_TYPE

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# 提前保存引用，避免类内部 uuid 列名遮蔽模块
_uuid4 = uuid.uuid4


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_conversations_platform_external"),
        UniqueConstraint("uuid", name="uq_conversations_uuid"),
        UniqueConstraint("job_id", name="uq_conversations_job_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    # 平台：boss / lagou / 51job
    platform: Mapped[str] = mapped_column(String(30), nullable=False, default="boss", server_default=text("'boss'"))
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # 平台侧聊天 ID（同步锚点），external_id 保留兼容
    external_chat_id: Mapped[str | None] = mapped_column(String(100))
    uuid: Mapped[UUID_TYPE] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        default=_uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # LangGraph thread_id，默认等于 uuid（1:1）
    thread_id: Mapped[UUID_TYPE] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        default=_uuid4,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("jobs.id"))
    hr_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("hrs.id"))
    hr_name: Mapped[str | None] = mapped_column(String(100))
    job_title: Mapped[str | None] = mapped_column(String(200))
    # 状态：active / waiting_hr / closed（doc 05）
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default=text("'active'")
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 附加字段，避免与 SQLAlchemy 保留属性 metadata 冲突
    extra: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
