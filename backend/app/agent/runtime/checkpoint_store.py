"""Checkpoint 存储（doc 06 §8）。

职责分两块，都在本模块内：

1. **生产存档器生命周期**（`CheckpointStore` 作为 async 上下文管理器持有）：
   包装 `AsyncPostgresSaver`（langgraph-checkpoint-postgres），让 LangGraph 图
   在执行每个节点后把状态落到 PostgreSQL（表 `checkpoints` / `checkpoint_writes`
   / `checkpoint_blobs` 由 saver.setup() 自建），进程重启后可经 thread_id 续跑。

   为什么用**单个长存活连接**而非连接池：
   WorkflowEngine 有执行锁，同一时刻至多一个任务在跑，checkpoint 写入不会并发，
   一个常驻连接足够；`AsyncPostgresSaver.from_conn_string` 因内部用
   `async with`（AsyncConnection）管理连接，必须由本类以 `__aenter__/__aexit__`
   方式把连接的生命周期对齐到整个应用生命周期，否则存档器一退出作用域连接即关闭。

2. **业务索引**（task_checkpoint_index 映射）：
   LangGraph 的 checkpoint 表只有 thread_id（UUID）能定位，业务侧想"凭任务号找回
   续跑点"需自建轻量映射 `task_id ↔ thread_id ↔ checkpoint_id`。本类用现有
   `TaskCheckpointIndexRepository` + 短会话管理该索引（登记录入 / 按任务查询 /
   终态标记 / 清理）。

依赖方向（对齐 CLAUDE.md 强制分层）：
   本模块 -> Repository/Repository 基类 -> session_factory -> DB；
   不反向依赖 runtime/graph（引擎经 checkpointer 属性取存档器，不感知存 PG）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, cast
from uuid import UUID as UUID_TYPE

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.base import get_session_factory
from app.models.task_checkpoint_index import TaskCheckpointIndex
from app.repository.task_checkpoint_index import TaskCheckpointIndexRepository

logger = logging.getLogger(__name__)

# 业务索引状态（doc 09 §5.14）：active 任务进行中 / terminal 任务终态
_ACTIVE = "active"
_TERMINAL = "terminal"


@dataclass(slots=True, frozen=True)
class CheckpointAnchor:
    """业务索引单条记录的 DTO（不泄露 ORM Model，规则：DTO 不泄露 ORM Model）。

    thread_id 存的是 LangGraph 线程锚点字符串（= str(任务 DB 的 thread_id UUID)），
    供 resume() 续跑直接使用。
    """

    task_id: int
    thread_id: str
    checkpoint_id: str | None
    status: str


class CheckpointStore:
    """存档器生命周期 + 业务索引管理者。

    用法（生产装配，FastAPI lifespan 内）：:

        async with CheckpointStore() as store:
            engine = WorkflowEngine(llm, checkpointer=store.checkpointer, ...)
            # 整个应用生命周期内，store 持有的涨活连接不关闭

    DI 要点（对齐引擎的测试注入风格，全部可选、可单测）：
    - ``session_factory``：默认全局单例；测试传假的会话工厂。
    - ``repo_factory``：默认产 TaskCheckpointIndexRepository；测试传假 Repository，
      使索引逻辑无需真实 PG 即可覆盖。
    - ``saver_factory``：默认 None 时用 AsyncPostgresSaver.from_conn_string 连真库；
      测试传一个返回 mock 存档器的工厂（prod 连接不可达时经此跳过）。
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        repo_factory: Callable[[AsyncSession], TaskCheckpointIndexRepository] | None = None,
        saver_factory: Callable[[str], BaseCheckpointSaver[Any]] | None = None,
        dsn: str | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        # 收口默认仓库构造：TaskCheckpointIndexRepository(session) 本身即 Callable，免 lambda
        self._repo_factory = repo_factory or TaskCheckpointIndexRepository
        self._saver_factory = saver_factory
        self._dsn = dsn or get_settings().database_dsn
        # 内部态用 Any：真实现(AsyncPostgresSaver)与测试 mock 都带 setup()，
        # BaseCheckpointSaver 基类未声明 setup()，严格类型会误报 union-attr。
        # 公开插口仍以 checkpointer 属性收敛为 BaseCheckpointSaver[Any]。
        self._saver: Any = None
        # from_conn_string 返回 asyncgen 上下文管理器，需持有以对齐连接生命周期
        self._agcm: Any | None = None

    # ------------------------------------------------------------------
    # 生命周期（async 上下文管理器）
    # ------------------------------------------------------------------
    async def __aenter__(self) -> CheckpointStore:
        await self.setup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    @property
    def checkpointer(self) -> BaseCheckpointSaver[Any]:
        """供 WorkflowEngine(checkpointer=...) 注入的存档器（GraphRuntime 插口）。

        未构造前访问快速失败：装配顺序错误（lifespan 外取成型器）应立即暴露，
        而非拿到空存档器让图静默丢只读状态。
        """
        if self._saver is None:
            msg = "CheckpointStore 未 setup/未进入 async with：先 setup() 再取 checkpointer"
            raise RuntimeError(msg)
        return cast(BaseCheckpointSaver[Any], self._saver)

    async def setup(self) -> None:
        """构建存档器并建 checkpoint 表（幂等）。

        生产走 from_conn_string 的 asyncgen 上下文管理器并持有之（不随本方法退出
        而关闭连接）；测试经 saver_factory 注入 mock，跳过真连库。
        """
        if self._saver is not None:
            return
        if self._saver_factory is not None:
            self._saver = self._saver_factory(self._dsn)
        else:
            self._agcm = AsyncPostgresSaver.from_conn_string(self._dsn)
            self._saver = await self._agcm.__aenter__()
        # setup() 会跑 MIGRATIONS：按 thread_id 在 checkpoints 表建索引，幂等
        await self._saver.setup()

    async def aclose(self) -> None:
        """关闭存档器连接，清空状态（对齐引擎 dispose_engine 的幂等性）。"""
        if self._agcm is not None:
            await self._agcm.__aexit__(None, None, None)
            self._agcm = None
        self._saver = None

    # ------------------------------------------------------------------
    # 业务索引（task_checkpoint_index；短会话 + 显式 commit）
    # ------------------------------------------------------------------
    async def register(
        self,
        task_id: int,
        thread_id: UUID_TYPE,
        checkpoint_id: str | None = None,
    ) -> CheckpointAnchor | None:
        """登记/更新某任务当前续跑点（幂等，按 task_id+thread_id 去重）。

        thread_id 为业务 DB 的真 UUID（生产 TaskService.create 必定生成）；
        为 None 时（异常脏数据）无法入 UUID 索引列，诚实跳过并记日志，
        不伪造续跑点。
        """
        if thread_id is None:
            logger.warning("checkpoint register skipped: task has no thread_id", extra={"task_id": task_id})
            return None
        async with self._session_factory() as session:
            repo = self._repo_factory(session)
            existing = await repo.get_latest_by_task(task_id)
            if existing is not None and existing.thread_id == thread_id:
                # 同线程重复执行：仅刷新 checkpoint_id（若有新值），保持单行不膨胀
                if checkpoint_id is not None and existing.checkpoint_id != checkpoint_id:
                    await repo.update(existing.id, {"checkpoint_id": checkpoint_id})
                await session.commit()
                return self._to_anchor(existing, thread_id)
            row = await repo.create(
                {
                    "task_id": task_id,
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                    "status": _ACTIVE,
                }
            )
            await session.commit()
            logger.info(
                "checkpoint index registered",
                extra={"task_id": task_id, "thread_id": str(thread_id), "checkpoint_id": checkpoint_id},
            )
            return self._to_anchor(row, thread_id)

    async def lookup_by_task(self, task_id: int) -> CheckpointAnchor | None:
        """凭任务号找回最近续跑点（供重启后 resume 定位 LangGraph thread）。"""
        async with self._session_factory() as session:
            row = await self._repo_factory(session).get_latest_by_task(task_id)
        if row is None:
            return None
        thread_id = row.thread_id
        return self._to_anchor(row, thread_id)

    async def mark_terminal(self, task_id: int) -> None:
        """任务终态后把当前索引置 terminal，避免误当活跃续跑点。"""
        async with self._session_factory() as session:
            row = await self._repo_factory(session).get_latest_by_task(task_id)
            if row is None or row.status == _TERMINAL:
                return
            await self._repo_factory(session).mark_terminal(row.id)
            await session.commit()
            logger.info("checkpoint index marked terminal", extra={"task_id": task_id})

    async def cleanup_terminal(self, task_id: int, keep: int = 5) -> int:
        """清理任务终态索引，只保留最近 keep 条（doc 06 §8：终态保留最近 5 个）。

        Returns:
            实际删除的索引条数。
        """
        async with self._session_factory() as session:
            repo = self._repo_factory(session)
            terminal = await repo.list_by_filter(
                {"task_id": task_id, "status": _TERMINAL}, order_by="id", limit=None, skip=keep
            )
            pruned = 0
            for row in terminal:
                await repo.delete(row.id)
                pruned += 1
            await session.commit()
        if pruned:
            logger.info("checkpoint terminal rows pruned", extra={"task_id": task_id, "count": pruned})
        return pruned

    # ------------------------------------------------------------------
    # 私有
    # ------------------------------------------------------------------
    def _to_anchor(self, row: TaskCheckpointIndex, thread_id: UUID_TYPE) -> CheckpointAnchor:
        """ORM row -> DTO。thread_id 统一转 str（= LangGraph 续跑锚点）。"""
        return CheckpointAnchor(
            task_id=row.task_id,
            thread_id=str(thread_id),
            checkpoint_id=row.checkpoint_id,
            status=row.status,
        )
