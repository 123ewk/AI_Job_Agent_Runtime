"""FastAPI 应用入口。

启动：uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app import __version__
from app.api.v1.router import api_router
from app.api.ws import ws_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.db.base import dispose_engine
from app.schema.common import ErrorResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
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
    await dispose_engine()


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


def _build_error_response(
    error_code: str,
    message: str,
    *,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """按统一 ErrorResponse 格式构造错误响应。

    exclude_none=True：details/request_id 缺省时不下发，保持响应体干净。
    """
    body = ErrorResponse(
        error=error_code,
        message=message,
        details=details,
    ).model_dump(exclude_none=True)
    return JSONResponse(status_code=status_code, content=body)


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

    # ------------------------------------------------------------------
    # 全局异常处理器：把领域异常/HTTP 异常/未捕获异常统一成 ErrorResponse。
    # 注意：RequestValidationError（422）不在此列，保留 FastAPI 默认
    # {"detail": [...]} 契约，前端按惯例消费。
    # ------------------------------------------------------------------
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _build_error_response(
            exc.code, exc.message, status_code=exc.status_code, details=exc.details
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 覆盖 Starlette 默认 {"detail": ...}，统一为 ErrorResponse（含 404 路由未匹配）
        return _build_error_response("http_error", str(exc.detail), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unhandled_error(_: Request, exc: Exception) -> JSONResponse:
        # 兜底：记录完整堆栈，对外只暴露通用错误信息，避免泄露内部细节
        logger = get_logger("app.exceptions")
        logger.exception("unhandled_exception", exc_info=exc)
        return _build_error_response("internal_error", "服务器内部错误", status_code=500)

    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        """根路径，返回服务基本信息与文档地址。"""
        return {"app": settings.app_name, "version": __version__, "docs": "/docs"}

    return app


app = create_app()
