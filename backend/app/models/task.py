"""任务模型。

任务状态机（doc 03 / doc 09 §7）：
    pending -> running -> waiting_approval / recovering -> succeeded / failed / canceled
规则：一次执行一个 Agent 任务；多任务进入 Redis Stream 队列。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID as UUID_TYPE

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TaskStatus(StrEnum):
    """任务状态枚举（小写，与 doc 09 §7 对齐）。
    DB 层以 String + CheckConstraint 兜底校验。
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    RECOVERING = "recovering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskPriority(StrEnum):
    """任务优先级（doc 04 调度）。"""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_user_status", "user_id", "status"),
        Index("ix_tasks_thread_id", "thread_id"),
        Index("ix_tasks_priority_scheduled", "priority", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    # 任务类型：proactive_job / proactive_chat / hr_reply / approval_resume / sync / recovery
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=TaskStatus.PENDING.value,
        server_default=text("'pending'"),
    )
    # 绑定的 Thread（= conversation.uuid），LangGraph Checkpoint 锚点
    thread_id: Mapped[UUID_TYPE | None] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"))
    job_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("jobs.id"))
    # 优先级：P0（最高）~ P3（最低）
    priority: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default=TaskPriority.P2.value,
        server_default=text("'P2'"),
    )
    # 任务输入/输出，JSONB 便于结构化扩展
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    # max_retries 默认 2（与 Prompt 对齐，doc 09 §5.6）
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default=text("2"))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
