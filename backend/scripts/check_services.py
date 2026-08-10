"""基础设施连通性自检。

用法（在 backend/ 下）：
    uv run python scripts/check_services.py

逐个探测 PostgreSQL / Redis / MinIO，打印结构化结果。
退出码 0 表示全部就绪；非 0 表示至少一个失败，便于 CI 或启动脚本判断。

设计点：
- MinIO SDK 是同步的，用 run_in_executor 包裹，避免阻塞事件循环。
- 日志中只打印 host/db，不打印密码等敏感信息。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 让脚本可从 backend/ 任意位置直接运行：把 backend/ 加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import dispose_engine, get_engine

logger = get_logger("scripts.check_services")


async def check_postgres() -> tuple[bool, str]:
    """探测 PostgreSQL：SELECT 1 + 版本号。"""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
            version = (await conn.execute(text("SELECT version()"))).scalar_one()
            return True, f"ok: {version.split(',')[0]}"
    except Exception as exc:
        return False, f"error: {exc}"


async def check_redis() -> tuple[bool, str]:
    """探测 Redis：PING。"""
    settings = get_settings()
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            pong = await client.ping()
            return bool(pong), "ok: PONG"
        finally:
            await client.aclose()
    except Exception as exc:
        return False, f"error: {exc}"


async def check_minio() -> tuple[bool, str]:
    """探测 MinIO：列举 buckets。"""
    settings = get_settings()
    try:
        from minio import Minio

        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        # 同步 SDK，丢到线程池避免阻塞事件循环
        loop = asyncio.get_running_loop()
        buckets = await loop.run_in_executor(None, client.list_buckets)
        names = [b.name for b in buckets]
    except Exception as exc:
        return False, f"error: {exc}"
    else:
        return True, f"ok: buckets={names}"


async def main() -> int:
    configure_logging("INFO", json_render=False)
    settings = get_settings()
    # 只打印 host:port/db，避免泄漏密码
    db_target = settings.database_url.split("@")[-1]
    logger.info(
        "开始探测基础设施",
        env=settings.app_env.value,
        db=db_target,
        redis=settings.redis_url.split("@")[-1],
    )

    checks = {
        "postgres": check_postgres,
        "redis": check_redis,
        "minio": check_minio,
    }
    results: dict[str, bool] = {}
    for name, fn in checks.items():
        ok, detail = await fn()
        results[name] = ok
        logger.info("探测结果", component=name, ok=ok, detail=detail)

    await dispose_engine()

    all_ok = all(results.values())
    logger.info("探测完成", results=results, all_ok=all_ok)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
