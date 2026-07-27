"""执行日志模型（append-only）。

字段依据技术栈文档：task_id / node / tool / input / output / error。
额外加 latency_ms 便于性能分析。日志只追加，不混入 updated_at。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    __table_args__ = (Index("ix_execution_logs_task_created", "task_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tasks.id"), nullable=False)
    # LangGraph 节点名：job_analyze / response_planner / tool_executor 等
    node: Mapped[str | None] = mapped_column(String(100))
    tool: Mapped[str | None] = mapped_column(String(100))
    input: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    output: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
