"""锁管理（doc 04 §8 并发与锁）。

两级锁，获取顺序固定：执行锁 -> 浏览器锁，禁止反向（§8.5 死锁防范）。
- 执行锁：全局单任务保证。V1 进程内 asyncio.Lock（§8.1）；Approval 挂起
  期间**不释放**（V1 简化：严格单任务，暂停不释放锁）。
- 浏览器锁：Chrome 是单实例共享资源，所有 MCP 工具调用必须串行（§8.4），
  由 SkillExecutor（tools/router.py）在调用前后包住。

并发安全说明：
- asyncio.Lock 非重入：嵌套获取同种锁会死锁，属编程错误（§8.5 明令禁止）。
- asyncio.Lock 不绑定持有者：release 可能由"另一协程"发出--这是有意利用
  的特性（run() 挂起后由 resume() 路径释放），但也意味着必须由 LockManager
  的调用方保证 acquire/release 配对，不能依赖运行时校验。
- 所有获取带超时，超时抛 LockTimeoutError 上抛而非死等（§17：Lock 超时 ->
  任务转 recovering/failed）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# 执行锁等待上限：覆盖"等上一个任务跑完"的最长情形，超时说明上游该重排队
EXECUTION_LOCK_TIMEOUT = 600.0
# 浏览器锁等待上限：覆盖单次 MCP 调用（页面操作可达数十秒），超时上抛
BROWSER_LOCK_TIMEOUT = 120.0


class LockTimeoutError(RuntimeError):
    """锁获取超时（doc 04 §17：上抛给调用方决策，而非死等）。"""


class LockManager:
    """进程内锁集合。

    V1 单 Worker 语义；多 Worker 扩容时替换为 Redis 分布式锁
    （lock:agent:execute，TTL + 续约，doc 04 §19），接口形状保持不变。
    """

    def __init__(self) -> None:
        self._execution_lock = asyncio.Lock()
        self._browser_lock = asyncio.Lock()

    @property
    def execution_locked(self) -> bool:
        """执行锁当前是否被持有（诊断与测试断言用）。"""
        return self._execution_lock.locked()

    # ------------------------------------------------------------------
    # 执行锁：手动 acquire/release（挂起跨协程持有的唯一合法场景）
    # ------------------------------------------------------------------
    async def acquire_execution(self, timeout: float = EXECUTION_LOCK_TIMEOUT) -> None:
        """获取执行锁；Interrupt 挂起期间保持持有，由 resume 终态路径释放。"""
        try:
            await asyncio.wait_for(self._execution_lock.acquire(), timeout=timeout)
        except TimeoutError as exc:
            msg = f"execution lock acquire timeout after {timeout}s"
            raise LockTimeoutError(msg) from exc

    def release_execution(self) -> None:
        """释放执行锁（未持有时为 no-op，容忍崩溃恢复后的重复释放）。"""
        if self._execution_lock.locked():
            self._execution_lock.release()

    @asynccontextmanager
    async def execution(self, timeout: float = EXECUTION_LOCK_TIMEOUT) -> AsyncIterator[None]:
        """执行锁上下文模式：run-to-terminal 场景（不跨挂起）。"""
        await self.acquire_execution(timeout)
        try:
            yield
        finally:
            self.release_execution()

    # ------------------------------------------------------------------
    # 浏览器锁：仅上下文模式（持有范围 = 单次 MCP 调用，不存在跨挂起）
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def browser(self, timeout: float = BROWSER_LOCK_TIMEOUT) -> AsyncIterator[None]:
        """浏览器锁：SkillExecutor 调 MCP 前后包住（doc 04 §8.4）。

        调用方必须已持有执行锁（顺序固定：执行锁 -> 浏览器锁）。
        """
        try:
            await asyncio.wait_for(self._browser_lock.acquire(), timeout=timeout)
        except TimeoutError as exc:
            msg = f"browser lock acquire timeout after {timeout}s"
            raise LockTimeoutError(msg) from exc
        try:
            yield
        finally:
            self._browser_lock.release()
