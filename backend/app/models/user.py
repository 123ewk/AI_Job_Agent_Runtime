"""用户模型。

承载用户基本信息与设置（spec Phase 1 Settings：LLM / API Key / 自动回复 / 自动投递 /
并发数量 / 回复风格）。API Key 以加密形式存储，禁止明文落库。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    nickname: Mapped[str | None] = mapped_column(String(100))
    # 认证相关；Phase 2 接入 JWT 时填充
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # 用户级 LLM 配置，覆盖全局默认
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    llm_base_url: Mapped[str | None] = mapped_column(String(500))
    llm_api_key_encrypted: Mapped[str | None] = mapped_column(String(500))
    llm_model: Mapped[str | None] = mapped_column(String(100))
    # 灵活设置项，保留兼容；settings 表为权威入口，此处为缓存/兼容层
    settings: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 用户备注/简介，便于 Agent 个性化回复
    bio: Mapped[str | None] = mapped_column(Text)
