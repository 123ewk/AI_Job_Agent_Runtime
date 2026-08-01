"""Task-Checkpoint 索引模型（doc 09 §5.14）。

LangGraph 的 Checkpoint 表由 AsyncPostgresSaver 自动创建管理
（checkpoints / checkpoint_writes / checkpoint_blobs），
业务侧不直接操作。本表为轻量索引，桥接 task_id 与 thread_id/checkpoint_id，
便于：
- 按 task_id 查询最近 Checkpoint
- 清理策略（终态保留最近 N 个）
- 断点续跑入口定位
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as UUID_TYPE

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskCheckpointIndex(Base):
    """Task 与 LangGraph Checkpoint 的映射索引。

    status: active（任务进行中，活跃 Checkpoint）/ terminal（任务终态）
    """

    __tablename__ = "task_checkpoint_index"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # LangGraph thread_id（= conversation.uuid）
    thread_id: Mapped[UUID_TYPE] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # LangGraph checkpoint_id（字符串标识）
    checkpoint_id: Mapped[str | None] = mapped_column(String(100))
    # active / terminal
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
