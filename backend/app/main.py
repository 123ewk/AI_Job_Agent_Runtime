"""FastAPI 应用入口。

启动：uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import engine

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期。

    启动期：配置结构化日志。
    关闭期：释放数据库连接池，避免连接泄漏。
    """
    configure_logging(settings.log_level, json_render=not settings.is_dev)
    logger = get_logger("app.lifecycle")
    logger.info(
        "应用启动",
        app=settings.app_name,
        env=settings.app_env.value,
        version=__version__,
    )
    yield
    logger.info("应用关闭，释放数据库连接池")
    await engine.dispose()


def _build_cors_origins() -> list[str]:
    """构建 CORS 白名单。

    dev 环境自动放行本地 Vite 开发端口；生产环境只允许 .env 显式配置的域名。
    注意：allow_credentials=True 时不能用通配 "*"，故必须显式列表。
    """
    origins = list(settings.cors_origins_list)
    if settings.is_dev:
        origins.extend(
            [
                "http://localhost:5173",
                "http://localhost:5174",
                "http://127.0.0.1:5173",
                "http://127.0.0.1:5174",
            ]
        )
    return origins


def create_app() -> FastAPI:
    """应用工厂，便于测试时构造独立实例。"""
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="AI 求职 Agent 后端服务",
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_cors_origins(),
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        max_age=settings.cors_max_age_seconds,
    )

    app.include_router(api_router)

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        """根路径，返回服务基本信息与文档地址。"""
        return {"app": settings.app_name, "version": __version__, "docs": "/docs"}

    return app


app = create_app()
