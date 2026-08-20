"""LockManager 单元测试（doc 04 §8）。

不连 DB / 不连 Redis：纯 asyncio 并发行为验证（互斥、超时、异常释放）。
"""

import asyncio

import pytest

from app.agent.runtime.lock_manager import LockManager, LockTimeoutError


async def test_execution_lock_serializes_concurrent_sections() -> None:
    """执行锁互斥：两个并发临界区不重叠（单任务保证的底层机制）。"""
    locks = LockManager()
    order: list[str] = []

    async def section(name: str) -> None:
        async with locks.execution(timeout=5):
            order.append(f"{name}:enter")
            await asyncio.sleep(0.05)
            order.append(f"{name}:exit")

    await asyncio.gather(section("a"), section("b"))
    # a 完整先于 b（先获取者先执行），无交叉
    assert order == ["a:enter", "a:exit", "b:enter", "b:exit"]


async def test_browser_lock_acquire_timeout_raises() -> None:
    """浏览器锁被占时获取超时 -> LockTimeoutError 上抛（不死等）。"""
    locks = LockManager()
    async with locks.browser(timeout=0.05):
        with pytest.raises(LockTimeoutError):
            async with locks.browser(timeout=0.05):
                pass


async def test_execution_context_releases_on_exception() -> None:
    """临界区抛异常也必须释放锁（finally 语义，否则永久死锁）。"""
    locks = LockManager()
    boom = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        async with locks.execution(timeout=1):
            raise boom
    assert not locks.execution_locked


async def test_manual_release_without_holder_is_noop() -> None:
    """未持有时 release 为 no-op：容忍崩溃恢复后的重复释放。"""
    locks = LockManager()
    locks.release_execution()  # 不抛即通过
    assert not locks.execution_locked


async def test_manual_acquire_release_across_suspension() -> None:
    """手动模式：挂起场景跨协程持有与释放（run 挂起 -> resume 释放）。"""
    locks = LockManager()
    await locks.acquire_execution(timeout=1)
    assert locks.execution_locked

    # 模拟 Interrupt 挂起后由另一协程（resume 路径）释放
    await asyncio.sleep(0)
    locks.release_execution()
    assert not locks.execution_locked
