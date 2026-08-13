"""异步数据库引擎与会话工厂（惰性初始化）。

设计动机：
- engine 与 session_factory 采用惰性创建：首次调用 get_engine() 时才实例化，
  避免模块 import 阶段绑定到「当时正在运行的事件循环」。
- 这对 pytest-asyncio 尤为关键：collection 阶段（import conftest/app）已存在
  运行中的事件循环，若此时创建 engine，asyncpg 连接池会绑定到 collection
  循环；而测试运行在另一个循环，于是报
  "Task got Future attached to a different loop"。
- 惰性化后，engine 绑定到首次实际使用它的循环（生产=uvicorn worker 循环）。
- 全进程共享一个 engine（连接池），async_sessionmaker 产出每请求一个
  AsyncSession，请求结束关闭。
- pool_pre_ping=True 防止使用已被数据库侧断开的陈旧连接（长连接超时场景）。
- expire_on_commit=False 让提交后仍可访问 ORM 对象属性，避免 lazy load
  触发隐式 IO。
- Base 是所有 ORM 模型的声明式基类；TimestampMixin 统一 created_at/updated_at。

并发安全说明：
- get_engine() 是同步函数、内部无 await。asyncio 单线程循环中协程仅在 await
  点切换，check-then-create-then-assign 之间无 await，对同一循环内的协程
  天然原子，不会产生竞态。
- 但历史上 TestClient 会把 ASGI app 跑在独立线程的独立循环中，存在跨线程
  首次调用 get_engine() 的可能。故用 threading.Lock + double-checked
  locking 防御多线程竞态；持锁期间只执行同步的 create_async_engine
  （微秒级），不会实质阻塞事件循环。
- 用 _State 容器类的属性赋值管理单例，而非 global 语句重绑定模块变量，
  既避免 PLW0603 告警，又保持可变状态的显式封装。
"""

from __future__ import annotations

from datetime import datetime
from threading import Lock

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings


class _State:
    """惰性单例状态容器。

    engine 创建本身不绑定事件循环，asyncpg 连接池在首次连接时绑定，
    因此惰性创建确保绑定的是「首次使用时正在运行的循环」。
    """

    engine: AsyncEngine | None
    session_factory: async_sessionmaker[AsyncSession] | None

    def __init__(self) -> None:
        self.engine = None
        self.session_factory = None


_state = _State()
_init_lock = Lock()


def get_engine() -> AsyncEngine:
    """获取全局异步引擎单例（惰性创建）。

    首次调用时按当前 settings 创建 engine 并缓存，后续返回同一实例。
    double-checked locking 保证多线程并发首次调用只创建一次。

    Returns:
        全局 AsyncEngine 单例。
    """
    if _state.engine is None:
        with _init_lock:
            if _state.engine is None:  # 二次检查：拿到锁后可能已被其他线程初始化
                settings = get_settings()
                _state.engine = create_async_engine(
                    settings.database_url,
                    echo=settings.debug,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=10,
                )
    return _state.engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取会话工厂单例（惰性创建，绑定到惰性 engine）。

    Returns:
        全局 async_sessionmaker 单例。
    """
    if _state.session_factory is None:
        # 先在锁外取 engine：get_engine() 自带 double-checked locking，线程安全。
        # 若在持有 _init_lock 时调用 get_engine()，冷启动首请求会因同一线程重复
        # 获取非重入 threading.Lock 而自死锁（生产首个触 DB 的请求必现，2026-08-13
        # 已修复，见 docs/issues/2026-08-13-db-engine-lazy-init-self-deadlock.md）。
        # 锁内只创建 async_sessionmaker（微秒级），符合惰性初始化设计意图。
        engine = get_engine()
        with _init_lock:
            if _state.session_factory is None:
                _state.session_factory = async_sessionmaker(
                    bind=engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                )
    return _state.session_factory


async def dispose_engine() -> None:
    """释放引擎连接池并清空单例。

    应用关闭时调用，避免连接泄漏；测试间重置时调用，避免跨事件循环复用
    旧 engine。释放后下次 get_engine() 会按当前循环重新创建。
    """
    with _init_lock:
        if _state.engine is not None:
            await _state.engine.dispose()
        _state.engine = None
        _state.session_factory = None


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
