"""API 层公共依赖。

依赖方向：api -> service -> repository -> database。
此处仅提供跨层的基础设施依赖（DB 会话、配置），不写业务逻辑。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.base import async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """注入数据库会话。

    每个请求一个独立 AsyncSession，请求结束自动关闭。
    even 在请求处理抛异常时，async with 也会确保 session.close() 执行，
    避免连接泄漏。
    """
    async with async_session_factory() as session:
        yield session


def get_app_settings() -> Settings:
    """注入 Settings 单例。"""
    return get_settings()
