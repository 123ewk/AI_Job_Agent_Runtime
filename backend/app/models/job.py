"""岗位模型。

score 为匹配总分（BM25 + 语义加权），score_detail 存权重明细，
便于复盘匹配模块（.env MATCH_BM25_WEIGHT / MATCH_SEMANTIC_WEIGHT）。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_jobs_platform_external"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(200))
    salary: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    score: Mapped[float | None] = mapped_column(Float)
    score_detail: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    # 状态：discovered / analyzed / applied / rejected
    status: Mapped[str | None] = mapped_column(String(30))
    extra: Mapped[dict[str, object] | None] = mapped_column(JSONB)
