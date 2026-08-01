"""简历模型。

embedding 用 pgvector 存储句向量，模型为 bge-small-zh-v1.5（维度 512），
用于语义匹配与长期记忆检索。file_key 指向 MinIO 对象。
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Resume(Base, TimestampMixin):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(100))
    # 版本号，支持多版本简历（doc 05）
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    # MinIO 对象 key 与可访问 URL
    file_key: Mapped[str | None] = mapped_column(String(255))
    file_url: Mapped[str | None] = mapped_column(String(500))
    # 解析后的纯文本，用于向量化与 Agent 引用
    content: Mapped[str | None] = mapped_column(Text)
    # embedding 已迁移至 resume_summaries 表，此处保留兼容（逐步废弃）
    embedding: Mapped[list[float] | None] = mapped_column(Vector(512))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # 状态：draft / active / archived（doc 05）
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default=text("'active'")
    )
