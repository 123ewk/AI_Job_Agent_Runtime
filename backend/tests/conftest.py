"""pytest 全局配置与 Fixture。

核心设计：使用 httpx.AsyncClient + ASGITransport 在「同一事件循环」内驱动
ASGI app，这是 async FastAPI 测试的正解。

为什么不用 TestClient：
- TestClient 在独立线程的独立事件循环里跑 ASGI app；而测试 fixture 创建的
  engine 处于 pytest-asyncio 的循环。asyncpg 连接池在首次连接时绑定事件
  循环，于是 app 请求循环 ≠ engine 绑定循环，运行时报
  "Task got Future attached to a different loop"。
- AsyncClient + ASGITransport 把 app 跑在进程内当前循环，fixture 与请求
  共享同一事件循环，彻底消除循环不匹配。

事件循环隔离：
- pytest-asyncio 1.x auto 模式默认 function 级循环（每测试一个新循环）。
- test_engine 为 function 级 fixture，每测试创建独立 engine + 建表，测试
  结束 drop + dispose，保证测试间数据与连接池完全隔离。

依赖覆盖策略：
- 覆盖 get_db：每请求从 test_session_factory 新开 session（绑定 test_engine，
  与请求同循环）。
- 覆盖 get_current_user_id：返回 seed_user 预置的用户 id。
- app 的惰性 engine 在测试中因 get_db 被覆盖而永远不会被创建，故无需重置。
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from enum import StrEnum
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 测试用 PostgreSQL 连接串（与开发库隔离）
TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/copilot_test"

# 在导入任何 app 模块前，先标记测试环境
os.environ["TESTING"] = "1"


# ---------------------------------------------------------------------------
# Mock Settings（必须在导入 app 模块前生效）
# ---------------------------------------------------------------------------
class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class MockSettings:
    """测试用 Settings mock。

    覆盖 get_settings 返回此对象，使 app 全部走测试库与测试 Redis（DB 1），
    避免污染开发数据。
    """

    database_url = TEST_DB_URL
    redis_url = "redis://localhost:6379/1"
    app_name = "AI Career Copilot (Test)"
    app_env = AppEnv.TEST
    debug = True
    log_level = "WARNING"
    cors_allow_origins = ""
    cors_allow_extensions = True
    cors_allow_credentials = True
    cors_max_age_seconds = 600
    # 敏感配置加密密钥（api_key 加密用），测试环境固定值以便解密断言
    jwt_secret_key = "test-secret"  # noqa: S105 - 测试 mock 固定密钥，非真实凭据
    # 浏览器桥：默认关闭，测试不 spawn node 子进程
    browser_mcp_enabled = False
    browser_mcp_host = "127.0.0.1"
    browser_mcp_port = 12307
    browser_mcp_token = ""
    browser_mcp_server_path = ""
    browser_mcp_timeout = 30.0
    browser_mcp_ping_interval = 30.0
    browser_mcp_url_whitelist = "zhipin.com"
    browser_mcp_risk_tools = "chrome_javascript,chrome_network_request"
    browser_mcp_fallback_mode = "both"
    browser_mcp_fallback_max_steps = 3
    browser_mcp_routine_retry = 2

    @property
    def cors_origins_list(self) -> list[str]:
        return []

    @property
    def is_dev(self) -> bool:
        return False

    @property
    def browser_mcp_url_whitelist_list(self) -> list[str]:
        return [item.strip() for item in self.browser_mcp_url_whitelist.split(",") if item.strip()]

    @property
    def browser_mcp_risk_tools_list(self) -> list[str]:
        return [item.strip() for item in self.browser_mcp_risk_tools.split(",") if item.strip()]

    @property
    def browser_mcp_server_path_resolved(self) -> str:
        return self.browser_mcp_server_path or ""


# patch 必须在导入 app 模块前生效；模块级 start 保证后续 import app.* 时命中 mock
settings_patcher = patch("app.core.config.get_settings", return_value=MockSettings())
settings_patcher.start()

# 显式导入全部 ORM 模型，使其在 Base.metadata 中注册。
# 否则 test_engine 的 create_all 会在模型未注册时建出空库（relation does not exist）。
import app.models  # noqa: E402, F401


# ---------------------------------------------------------------------------
# 会话级一次性设置
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _configure_logging() -> None:
    """配置结构化日志（WARNING 级别降噪）。

    AsyncClient 不触发 app lifespan，故 lifespan 内的 configure_logging 不会执行；
    此处补一次，避免 Service 日志走到未配置的 structlog 默认输出。
    """
    from app.core.logging import configure_logging

    configure_logging("WARNING", json_render=False)


@pytest.fixture(scope="session", autouse=True)
def cleanup_patches() -> None:
    """会话结束时清理 settings patch，避免污染后续其他测试进程。"""
    yield
    settings_patcher.stop()


@pytest.fixture(autouse=True)
async def reset_redis() -> None:
    """每测试结束重置 Redis 客户端/连接池。

    pytest-asyncio 每测试一个独立事件循环，而 get_redis_client() 是进程级
    lru_cache 单例——首个测试的 enqueue 把连接绑定到该测试的循环，循环关闭后
    连接变为死连接，下个测试复用会报 "Event loop is closed"。故每测试结束
    关闭连接并清两个 lru_cache，让下个测试在新循环内重建池。
    生产（uvicorn 单循环）不受影响。
    """
    yield
    from app.infra.redis import get_redis_client, get_redis_pool

    client = get_redis_client()
    await client.aclose()
    get_redis_client.cache_clear()
    get_redis_pool.cache_clear()


# ---------------------------------------------------------------------------
# DB engine / session（测试专用，独立于 app 的惰性 engine）
# ---------------------------------------------------------------------------
@pytest.fixture
async def test_engine() -> AsyncGenerator[object, None]:
    """每测试一个独立 DB engine，负责建表/清表。

    function 级作用域确保每测试的事件循环与 engine 一一对应。
    """
    from app.db.base import Base

    engine = create_async_engine(TEST_DB_URL, echo=False, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_engine: object) -> async_sessionmaker[AsyncSession]:
    """绑定到 test_engine 的会话工厂。

    供 repository 测试的 test_session 与 API 测试的 get_db 覆盖共用，
    确保同一测试内所有 session 指向同一 engine（同一循环）。
    """
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def test_session(test_session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    """测试用 DB Session（repository 测试依赖）。

    yield 后 rollback 丢弃未提交变更；async with 自动 close 释放连接。
    """
    async with test_session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# API 测试客户端（httpx.AsyncClient + ASGITransport）
# ---------------------------------------------------------------------------
@pytest.fixture
async def seed_user(test_session_factory: async_sessionmaker[AsyncSession]) -> int:
    """预置测试用户，返回其 id。

    API 测试默认以该用户身份发起请求（覆盖 get_current_user_id）。
    """
    from app.models import User

    async with test_session_factory() as session:
        user = User(email="test@example.com")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.fixture
async def client(
    test_session_factory: async_sessionmaker[AsyncSession],
    seed_user: int,
) -> AsyncGenerator[AsyncClient, None]:
    """异步测试客户端。

    ASGITransport 让 app 跑在当前事件循环，与 test_session_factory 的 engine
    同循环，消除 TestClient 的跨循环问题。覆盖 get_db / get_current_user_id
    使请求走测试 session 与预置用户。
    """
    from app.api.deps import get_current_user_id, get_db
    from app.main import create_app

    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        # 每请求新开 session，绑定 test_engine（与请求同循环）
        async with test_session_factory() as session:
            yield session

    async def override_get_current_user_id() -> int:
        return seed_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = override_get_current_user_id

    # raise_app_exceptions=False：未捕获异常交给 Starlette ServerErrorMiddleware 转成
    # 500 响应（与生产 uvicorn 行为一致）。默认 True 会把异常直接抛回测试进程，
    # 导致断言 `>= 400` 的 not_found 测试拿到 ValueError 而非 500 响应。
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
