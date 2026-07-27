"""异步数据库引擎与会话工厂。

设计动机：
- 全进程共享一个 async engine（连接池），避免每次请求新建连接造成资源泄漏。
- async_sessionmaker 产出 AsyncSession，每个请求一个独立会话，请求结束关闭。
- Base 是所有 ORM 模型的声明式基类；TimestampMixin 统一 created_at/updated_at。
- pool_pre_ping=True 防止使用已被数据库侧断开的陈旧连接（长连接超时场景）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

settings = get_settings()

# 异步引擎：asyncpg 驱动，不阻塞事件循环
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

# 会话工厂：expire_on_commit=False 让提交后仍可访问 ORM 对象属性（避免 lazy load 触发隐式 IO）
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class TimestampMixin:
    """统一时间戳字段。

    所有业务表混入此 Mixin，保证审计字段一致。
    使用带时区的 TIMESTAMPTZ，存储 UTC 时间。
    """

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """产出数据库会话。

    作为 FastAPI 依赖使用：每次请求获取独立会话，请求结束自动关闭。
    使用 yield 语法确保 even 在异常时也会执行 close（finally 语义）。
    """
    async with async_session_factory() as session:
        yield session
