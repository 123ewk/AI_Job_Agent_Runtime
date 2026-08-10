"""Redis 客户端工厂。

设计动机：
- 统一 Redis 连接管理，避免各模块重复创建连接池
- 支持懒加载与单例模式，减少连接数
- 与 Settings 解耦，便于测试 mock

核心机制：
- 使用 redis.asyncio.Redis 创建异步连接池
- get_redis_client() 带 lru_cache，保证进程内单例
- 所有 QueueClient/LockManager/Scheduler 共享同一连接池
"""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import ConnectionPool, Redis

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_redis_pool() -> ConnectionPool:
    """获取 Redis 连接池（单例）。

    lru_cache 保证进程内仅创建一个连接池，避免连接泄漏。
    连接池参数采用保守默认值，高并发场景可通过 Settings 扩展。
    """
    settings = get_settings()
    return ConnectionPool.from_url(
        settings.redis_url,
        max_connections=50,        # 单进程连接上限
        socket_timeout=5.0,        # 操作超时防死等
        socket_connect_timeout=3.0,  # 连接超时
        retry_on_timeout=True,     # 超时自动重试一次
        decode_responses=True,     # 自动 bytes -> str 解码
    )


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    """获取 Redis 客户端（单例）。

    所有需要 Redis 访问的模块均应通过此函数获取客户端，
    共享同一连接池，减少 TCP 握手开销。
    """
    pool = get_redis_pool()
    return Redis(connection_pool=pool)
