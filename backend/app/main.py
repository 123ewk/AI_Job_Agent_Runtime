"""FastAPI 应用入口。

启动：uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app import __version__
from app.agent.runtime.checkpoint_store import CheckpointStore
from app.agent.runtime.engine_registry import clear_runtime_engine, set_runtime_engine
from app.agent.runtime.lock_manager import LockManager
from app.agent.runtime.queue_consumer import QueueConsumer
from app.agent.runtime.workflow_engine import WorkflowEngine, create_planner_from_settings
from app.agent.tools.fallback import create_fallback_llm_from_settings
from app.agent.tools.router import SkillExecutor
from app.agent.tools.routine import RoutineRegistry
from app.api.v1.router import api_router
from app.api.ws import ws_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.db.base import dispose_engine, get_session_factory
from app.infra.browser_mcp import get_browser_mcp
from app.infra.queue import get_queue_client
from app.schema.common import ErrorResponse
from app.service.browser_tools import BrowserToolAdapter

settings = get_settings()

# V1 单用户模式：未接 JWT，全程固定 user_id=1（对齐 api/deps.get_current_user_id）
_DEFAULT_USER_ID = 1


@dataclass
class _AgentRuntime:
    """装配好的 agent 运行时（lifespan 持有，关闭期回收）。

    - ``engine``：WorkflowEngine 单例（含执行锁与挂起态），挂到 app.state.agent_engine，
      供 ApprovalService._resume_task 等经同一实例续跑。
    - ``store``：CheckpointStore，长存活存档器连接随应用生命周期开合。
    - ``consumer_task``：后台消费循环任务，关闭期 cancel 并回收。
    """

    engine: WorkflowEngine
    store: CheckpointStore
    consumer_task: asyncio.Task[Any]


async def _assemble_agent_runtime(app: FastAPI) -> _AgentRuntime:
    """装配 agent 引擎单例并启动后台消费循环（lifespan 启动期调用）。

    依赖链：CheckpointStore（持 AsyncPostgresSaver + 业务索引）-> create_planner
    （读用户 LLM 配置）-> WorkflowEngine（编译图，checkpointer=store.checkpointer）
    -> QueueConsumer -> 后台 run_forever 任务。

    SkillExecutor 接线（doc 17 例程 + 兜底）：共享 LockManager 给引擎（执行锁）
    与 SkillExecutor（浏览器锁，doc 04 §8.4）；浏览器桥启用时注入真实 adapter，
    未启用时注入 None（SkillExecutor 返回「未启用」错误，不崩）。

    失败兜底：任一步失败（LLM 未配置 / DB/Redis 暂不可达）直接上抛，由 lifespan
    捕获并跳过 agent 执行能力——HTTP API 主体仍正常启动，不因编排层故障拖垮服务。
    """
    store = CheckpointStore()
    await store.setup()  # 建 checkpoint 表（幂等）；DB 不可达在此抛
    locks = LockManager()
    planner = await create_planner_from_settings(
        get_session_factory(), user_id=_DEFAULT_USER_ID
    )
    if settings.browser_mcp_enabled:
        browser_mcp = await get_browser_mcp(settings)
        adapter = BrowserToolAdapter(client=browser_mcp, settings=settings)
        # LLM 兜底从用户 Settings.llm 装配（未配置返回 None -> 兜底自动降级为 adaptive）
        fallback_llm = await create_fallback_llm_from_settings(
            get_session_factory(), user_id=_DEFAULT_USER_ID
        )
        skills = SkillExecutor(
            adapter=adapter,
            registry=RoutineRegistry(),
            locks=locks,
            fallback_llm=fallback_llm,
            settings=settings,
        )
    else:
        skills = SkillExecutor(adapter=None, locks=locks, settings=settings)
    engine = WorkflowEngine(planner, skills=skills, checkpointer=store.checkpointer, locks=locks)
    app.state.agent_engine = engine  # 供 WS 等触达同一引擎实例
    set_runtime_engine(engine)  # ApprovalService 经 service-locator 触达同引擎续跑
    queue = get_queue_client()
    await queue.ensure_consumer_groups()
    consumer = QueueConsumer(engine, queue=queue)
    consumer_task = asyncio.create_task(consumer.run_forever(), name="queue-consumer")
    return _AgentRuntime(engine=engine, store=store, consumer_task=consumer_task)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期。

    启动期：配置结构化日志；装 agent 引擎（CheckpointStore + planner + 消费循环）；
    若开启浏览器桥则拉起 Chrome MCP Server。关闭期：停消费任务、关存档器连接、
    停浏览器桥、释放数据库连接池。
    """
    configure_logging(settings.log_level, json_render=not settings.is_dev)
    logger = get_logger("app.lifecycle")
    logger.info(
        "应用启动",
        app=settings.app_name,
        env=settings.app_env.value,
        version=__version__,
        browser_mcp_enabled=settings.browser_mcp_enabled,
    )

    runtime: _AgentRuntime | None = None
    try:
        runtime = await _assemble_agent_runtime(_app)
    except Exception:
        # 编排层装配失败不阻断 API 服务：记录原因，仅剩 HTTP 路由可用（agent 不跑）
        logger.exception("Agent runtime 装配失败，跳过 agent 执行能力（API 仍可用）")

    browser_mcp = await get_browser_mcp(settings)
    if settings.browser_mcp_enabled:
        # 探测-复用-托管：端口已有健康 server 则复用，否则自己拉起并接管
        await browser_mcp.start()
    else:
        logger.info("浏览器桥未启用（BROWSER_MCP_ENABLED=false），跳过启动")

    try:
        yield
    finally:
        logger.info("应用关闭，释放资源")
        if runtime is not None:
            # 停消费循环并回收任务，避免 "Task was destroyed but it is pending" 告警
            runtime.consumer_task.cancel()
            # 回收任务避免 "Task was destroyed but it is pending" 告警
            with suppress(asyncio.CancelledError):
                await runtime.consumer_task
            await runtime.store.aclose()
            clear_runtime_engine()
        if settings.browser_mcp_enabled:
            await browser_mcp.stop()
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


def _build_cors_origin_regex() -> str | None:
    """构建 CORS origin 正则。

    cors_allow_extensions=True 时放行浏览器扩展来源（chrome/moz/edge-extension://*），
    供扩展 popup/sidepanel/options 页面直接 fetch 后端（与 host_permissions 双保险）。
    allow_origins 无法列出动态的扩展 ID，只能用 regex。
    """
    if settings.cors_allow_extensions:
        return r"^(chrome|moz|edge)-extension://[a-p]{32}$"
    return None


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
        allow_origin_regex=_build_cors_origin_regex(),
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
