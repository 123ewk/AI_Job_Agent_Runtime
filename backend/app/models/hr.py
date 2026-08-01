"""HR 模型（doc 05 规范化）。

HR 为独立实体，同 HR 不同岗位 = 不同 Conversation。
Phase 0 仅 denorm hr_name 于 conversations，此处抽为独立表。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class HR(Base, TimestampMixin):
    """HR 信息。

    以 (user_id, platform, external_id) 为唯一键去重，
    避免同一 HR 出现在多个 Conversation 中产生冗余。
    """

    __tablename__ = "hrs"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "external_id", name="uq_hrs_user_platform_ext"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(
        String(30), nullable=False, default="boss", server_default=text("'boss'")
    )
    # 平台侧 HR ID（同步去重锚点）
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    company: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[str | None] = mapped_column(String(200))
