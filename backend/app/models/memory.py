"""长期记忆模型（doc 04 §11 / doc 09 §5.10）。

存储求职过程中的长期上下文，按 user 维度 + 可选 conversation/job 关联。
pgvector 语义检索 Top-K 注入 Planner。

类型（doc 09 §5.10）：
- preference:  用户偏好
- hr_pact:    HR 潜规则/约定
- interview:   面试经验
- decision:    决策记录
- fact:        事实信息
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Memory(Base):
    """长期记忆条目。

    embedding 维度 512（bge-small-zh），用于语义检索。
    user_id 必填；conversation_id / job_id 可选关联。
    """

    __tablename__ = "memory"
    __table_args__ = (
        Index("ix_memory_user", "user_id"),
        Index("ix_memory_user_conv", "user_id", "conversation_id"),
        # 向量索引（ivfflat, lists=100）在迁移脚本中用 SQL 原生创建
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"))
    job_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("jobs.id"))
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 512 维向量（bge-small-zh）
    embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
