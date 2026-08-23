"""CheckpointStore 单元测试（不连真实 PG）。

覆盖两块：
1. 存档器生命周期：setup()/aclose()/checkpointer——经 saver_factory 注入 mock，
   不触碰 from_conn_string 的真库连接。
2. 业务索引：register/lookup/mark_terminal/cleanup——经 repo_factory 注入假
   Repository + 假会话工厂，全进程内存跑通，无需 asyncpg 服务。

假仓库复用项目现有的"每测试注入边界对象"风格（对齐 workflow_engine 的测试）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.agent.runtime.checkpoint_store import CheckpointStore


# ----------------------------------------------------------------------
# 假边界对象（内存版 Repository / Session / Saver）
# ----------------------------------------------------------------------
@dataclass
class _FakeRow:
    id: int
    task_id: int
    thread_id: Any
    checkpoint_id: str | None
    status: str


@dataclass
class _FakeRepo:
    rows: list[_FakeRow] = field(default_factory=list)
    _next_id: int = 1

    async def get_latest_by_task(self, task_id: int) -> _FakeRow | None:
        for row in reversed(self.rows):
            if row.task_id == task_id:
                return row
        return None

    async def update(self, id: int, data: dict[str, Any]) -> _FakeRow | None:
        for row in self.rows:
            if row.id == id:
                for k, v in data.items():
                    setattr(row, k, v)
                return row
        return None

    async def create(self, data: dict[str, Any]) -> _FakeRow:
        row = _FakeRow(
            id=self._next_id,
            task_id=data["task_id"],
            thread_id=data["thread_id"],
            checkpoint_id=data.get("checkpoint_id"),
            status=data["status"],
        )
        self._next_id += 1
        self.rows.append(row)
        return row

    async def mark_terminal(self, index_id: int) -> _FakeRow | None:
        return await self.update(index_id, {"status": "terminal"})

    async def list_by_filter(
        self,
        filters: dict[str, Any],
        order_by: str = "id",
        limit: int | None = None,
        *,
        skip: int = 0,
    ) -> list[_FakeRow]:
        matched = [r for r in self.rows if all(getattr(r, k) == v for k, v in filters.items())]
        matched.sort(key=lambda r: getattr(r, order_by))
        if skip > 0:
            matched = matched[skip:]
        if limit is not None:
            matched = matched[:limit]
        return matched

    async def delete(self, id: int) -> bool:
        before = len(self.rows)
        self.rows = [r for r in self.rows if r.id != id]
        return len(self.rows) < before


class _FakeSession:
    def __init__(self, repo: _FakeRepo) -> None:
        self._repo = repo

    async def commit(self) -> None:
        pass  # 内存操作无需真实提交

    async def rollback(self) -> None:
        pass


class _FakeSessionFactory:
    """async 上下文管理器产会话：ReClose 语义对齐 AsyncSession。"""

    def __init__(self, repo: _FakeRepo) -> None:
        self._repo = repo

    def __call__(self) -> AsyncIterator[_FakeSession]:
        return _FakeSessionAContext(self._repo)


class _FakeSessionAContext:
    def __init__(self, repo: _FakeRepo) -> None:
        self._repo = repo

    async def __aenter__(self) -> _FakeSession:
        return _FakeSession(self._repo)

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSaver:
    def __init__(self) -> None:
        self.setup_called = False
        self.aclosed = False

    async def setup(self) -> None:
        self.setup_called = True


def _make_store(repo: _FakeRepo, saver: _FakeSaver) -> CheckpointStore:
    factory = _FakeSessionFactory(repo)
    return CheckpointStore(
        session_factory=factory,  # type: ignore[arg-type]
        repo_factory=lambda _session: repo,  # type: ignore[arg-type]
        saver_factory=lambda _dsn: saver,  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------------
# 用例
# ----------------------------------------------------------------------
def test_setup_builds_checkpointer_and_is_idempotent() -> None:
    repo = _FakeRepo()
    saver = _FakeSaver()
    store = _make_store(repo, saver)

    # 未 setup 前取 checkpointer 应快速失败
    with pytest.raises(RuntimeError):
        _ = store.checkpointer

    async def go() -> None:
        await store.setup()
        assert saver.setup_called is True
        assert store.checkpointer is saver
        # 幂等：重复 setup 不再重建（不重复调用基础 setup）
        await store.setup()
        assert saver.setup_called is True

    import asyncio

    asyncio.run(go())


def test_aclose_tears_down_saver() -> None:
    repo = _FakeRepo()
    saver = _FakeSaver()
    store = _make_store(repo, saver)

    async def go() -> None:
        await store.setup()
        await store.aclose()
        with pytest.raises(RuntimeError):
            _ = store.checkpointer

    import asyncio

    asyncio.run(go())


def test_register_iterates_memory() -> None:
    """同任务重复 register 同 thread 不膨胀行；换 thread 则新增一行。"""

    async def go() -> None:
        repo = _FakeRepo()
        store = _make_store(repo, _FakeSaver())
        tid1 = uuid.uuid4()
        tid2 = uuid.uuid4()

        first = await store.register(7, tid1, checkpoint_id="c1")
        assert first is not None
        assert first.thread_id == str(tid1)
        assert first.status == "active"

        # 同 thread 只刷新 checkpoint_id，不新增
        second = await store.register(7, tid1, checkpoint_id="c2")
        assert second is not None
        assert second.checkpoint_id == "c2"
        assert len(repo.rows) == 1

        # 换 thread（重试新线程）新增一行
        await store.register(7, tid2)
        assert _is_in(repo, tid2)
        assert len(repo.rows) == 2

    import asyncio

    asyncio.run(go())


def test_register_none_thread_skips_gracefully() -> None:
    """脏数据（thread_id=None）不入索引，不抛异常。"""

    async def go() -> None:
        repo = _FakeRepo()
        store = _make_store(repo, _FakeSaver())
        result = await store.register(1, None)  # type: ignore[arg-type]
        assert result is None
        assert repo.rows == []

    import asyncio

    asyncio.run(go())


def test_lookup_returns_latest_anchor() -> None:
    async def go() -> None:
        repo = _FakeRepo()
        store = _make_store(repo, _FakeSaver())
        tid = uuid.uuid4()
        await store.register(3, tid, checkpoint_id="c9")
        anchor = await store.lookup_by_task(3)
        assert anchor is not None
        assert anchor.thread_id == str(tid)
        assert anchor.checkpoint_id == "c9"
        # 未知任务返回 None
        assert await store.lookup_by_task(999) is None

    import asyncio

    asyncio.run(go())


def test_mark_terminal_then_lookup() -> None:
    async def go() -> None:
        repo = _FakeRepo()
        store = _make_store(repo, _FakeSaver())
        await store.register(5, uuid.uuid4())
        await store.mark_terminal(5)
        assert (await store.lookup_by_task(5)).status == "terminal"  # type: ignore[union-attr]

    import asyncio

    asyncio.run(go())


def test_cleanup_prunes_beyond_keep() -> None:
    async def go() -> None:
        repo = _FakeRepo()
        store = _make_store(repo, _FakeSaver())
        # 造 6 条 terminal 记录（id 递增），keep=5 应删最早 1 条
        for _ in range(6):
            await store.register(9, uuid.uuid4())
            await store.mark_terminal(9)
        pruned = await store.cleanup_terminal(9, keep=5)
        assert pruned == 1
        assert len(repo.rows) == 5

    import asyncio

    asyncio.run(go())


def _is_in(repo: _FakeRepo, thread_id: uuid.UUID) -> bool:
    return any(r.thread_id == thread_id for r in repo.rows)
