"""简历摘要模型（doc 09 §5.9）。

从 resumes 表拆分出 summary + embedding，支持多版本：
- 每次简历更新生成新 version，保留历史
- 向量索引建在此表上，resumes 表只存元数据
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResumeSummary(Base):
    """简历摘要与向量。

    (resume_id, version) 唯一；新增摘要时 version 递增，旧版本保留。
    embedding 维度 512（bge-small-zh），ivfflat 索引建在 DB 层。
    """

    __tablename__ = "resume_summaries"
    __table_args__ = (
        UniqueConstraint("resume_id", "version", name="uq_resume_summary_resume_version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    # 结构化摘要（LLM 生成，供 Agent 引用）
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # 512 维向量（bge-small-zh），用于语义匹配
    embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
