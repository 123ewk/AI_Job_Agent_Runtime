"""Service 基类。

提供所有 Service 共享的基础设施：
- AsyncSession 持有
- 事务装饰器
- 日志辅助
- 通用校验方法
"""

from __future__ import annotations

import asyncio
from functools import wraps
from typing import Callable, TypeVar, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., object])


class BaseService:
    """所有 Service 的基类。

    封装 DB 会话、日志、通用事务方法。
    Service 层不直接操作 ORM，而是委托给 Repository。
    """

    def __init__(self, db: AsyncSession) -> None:
        """初始化 Service。

        Args:
            db: 数据库会话，由 FastAPI Depends 注入，每个请求一个独立会话。
        """
        self.db = db
        self._logger: structlog.stdlib.BoundLogger | None = None

    @property
    def logger(self) -> structlog.stdlib.BoundLogger:
        """延迟初始化结构化日志器。

        包含 service_name 上下文字段，便于日志过滤。
        """
        if self._logger is None:
            self._logger = get_logger(f"service.{self.__class__.__name__}")
        return self._logger

    async def commit(self) -> None:
        """提交事务。

        封装 commit 便于统一处理提交失败的日志与重试逻辑。
        注意：Service 层负责事务边界，Repository 层不 auto-commit。
        """
        await self.db.commit()

    async def rollback(self) -> None:
        """回滚事务。

        异常捕获块中调用，保证数据一致性。
        """
        await self.db.rollback()

    async def refresh(self, instance: T) -> T:
        """刷新 ORM 实例状态。

        封装后便于统一处理刷新失败的场景。
        """
        await self.db.refresh(instance)
        return instance

    def log_with_context(self, level: int, message: str, **kwargs: object) -> None:
        """带上下文的结构化日志。

        自动附加 service_name，调用方只需传业务相关字段。
        """
        self.logger.log(level, message, **kwargs)


def transactional(func: F) -> F:
    """事务装饰器。

    应用于 Service 层方法，自动管理事务边界：
    - 方法正常返回时 commit
    - 方法抛出异常时 rollback 并重新抛出
    - 支持嵌套调用（使用 savepoint）
    - 记录事务耗时与异常日志

    使用方式：
        class MyService(BaseService):
            @transactional
            async def create_something(self, ...):
                ...

    设计原理：
    1. 装饰器在调用 Service 方法时自动包裹事务
    2. 嵌套调用时，内层使用 savepoint 而非独立事务
    3. AsyncSession.begin_nested() 创建 savepoint
    4. 最外层才真正 commit，内层只释放 savepoint

    为什么不用 FastAPI Depends：
    - Depends 只能在 Request 级别，无法覆盖 Service 间调用
    - 后台任务（如 Approval 超时）无 Request 上下文，需要自己管理事务
    """

    @wraps(func)
    async def wrapper(self: BaseService, *args: object, **kwargs: object) -> object:
        service_name = self.__class__.__name__
        method_name = func.__name__

        # 检查是否已在事务中（嵌套调用）
        in_transaction = self.db.in_transaction()

        if in_transaction:
            # 嵌套事务：使用 savepoint
            self.logger.debug(
                "nested_transaction_start(嵌套事务开始)",
                method=method_name,
                service=service_name,
            )
            try:
                async with self.db.begin_nested():
                    result = await func(self, *args, **kwargs)
                self.logger.debug(
                    "nested_transaction_commit(嵌套事务提交)",
                    method=method_name,
                    service=service_name,
                )
                return result
            except Exception as exc:
                self.logger.warning(
                    "nested_transaction_rollback(嵌套事务回滚)",
                    method=method_name,
                    service=service_name,
                    error=str(exc),
                )
                raise
        else:
            # 最外层事务：真正的 commit/rollback
            start_time = asyncio.get_event_loop().time()
            self.logger.debug(
                "transaction_start",
                method=method_name,
                service=service_name,
            )
            try:
                async with self.db.begin():
                    result = await func(self, *args, **kwargs)
                duration = asyncio.get_event_loop().time() - start_time
                self.logger.info(
                    "transaction_commit",
                    method=method_name,
                    service=service_name,
                    duration_ms=round(duration * 1000, 2),
                )
                return result
            except Exception as exc:
                duration = asyncio.get_event_loop().time() - start_time
                self.logger.error(
                    "transaction_rollback",
                    method=method_name,
                    service=service_name,
                    duration_ms=round(duration * 1000, 2),
                    error=str(exc),
                    exc_info=True,
                )
                raise

    return cast(F, wrapper)
