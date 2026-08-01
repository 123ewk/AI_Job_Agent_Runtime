"""设置模型（独立表，替代 users.settings JSONB）。

按 category + key 存储用户配置，支持：
- 分组校验（llm / job_rule / agent / reply_style）
- 按字段版本化
- API 分域 PUT（doc 10）

与 users.settings 的关系：settings 表为权威，users.settings 为兼容缓存。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Setting(Base):
    """用户配置键值对。

    category 区分配置域，与 API 路由一一对应（doc 10）：
    - llm:  LLM 提供商、base_url、model、api_key（加密后存 value JSONB）
    - job_rule:  求职规则（薪资、地点、加班等）
    - agent:  Agent 行为配置（并发数、自动回复开关等）
    - reply_style:  回复风格参数
    """

    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "key", name="uq_settings_user_cat_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    # JSONB 值：支持 string/number/bool/object 等类型化值
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
