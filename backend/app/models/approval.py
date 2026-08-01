"""人工确认模型。

敏感字段（doc 14）：salary / location / start_date / overtime /
outsourcing / offsite / probation_salary。20 秒提醒机制对应 expires_at。
状态（doc 09 §7）：pending / approved / denied / timed_out。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ApprovalStatus(StrEnum):
    """Approval 状态枚举（与 doc 09 §7 对齐，全小写）。"""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class ApprovalType(StrEnum):
    """Approval 类型枚举（doc 14 敏感信息分类）。"""

    SALARY = "salary"
    LOCATION = "location"
    START_DATE = "start_date"
    OVERTIME = "overtime"
    OUTSOURCING = "outsourcing"
    OFFSITE = "offsite"
    PROBATION_SALARY = "probation_salary"


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_user_status", "user_id", "status"),
        # 部分索引：加速超时扫描（doc 09 §5.11）
        Index(
            "ix_approvals_expires_pending",
            "expires_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tasks.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ApprovalStatus.PENDING.value,
        server_default=text("'pending'"),
    )
    # 决策结果：approve / deny / timeout（冗余于 status，但便于快速读）
    decision: Mapped[str | None] = mapped_column(String(20))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
