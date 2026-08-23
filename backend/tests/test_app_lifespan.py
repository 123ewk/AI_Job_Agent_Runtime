"""应用生命周期装配测试（lifespan 的 agent runtime 接线，不连真 DB/Redis）。

锁住两个行为（doc 04 装配语义）：
1. **优雅降级**：agent runtime 装配失败（LLM 未配置 / DB 暂不可达）时不阻断应用
   启动——lifespan 照常 yield，HTTP API 主体仍可用。
2. **关闭回收**：装配成功时，关闭期必须 cancel 后台消费任务 + 关闭 CheckpointStore
   长存活连接，避免 "Task was destroyed but it is pending" 与连接泄漏。

经 monkeypatch 替换 main._assemble_agent_runtime，绕过真实 DB/Redis/LLM 依赖。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from app.main import create_app


async def _run_lifespan() -> None:
    """完整跑一遍 lifespan（setup -> yield -> teardown）。"""
    app = create_app()
    async with app.router.lifespan_context(app):
        return


async def test_assembly_failure_does_not_block_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    """装配抛异常 -> lifespan 不抛，应用仍可启动。"""
    _config_missing = RuntimeError("LLM not configured / DB down")

    async def _boom(_app: FastAPI) -> object:
        raise _config_missing

    monkeypatch.setattr("app.main._assemble_agent_runtime", _boom)

    await _run_lifespan()  # 不应上抛


class _FakeStore:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeRuntime:
    """鸭子类型对应 _AgentRuntime：engine / store / consumer_task 三属性。"""

    def __init__(self) -> None:
        self.engine: object = object()
        self.store = _FakeStore()
        # 挂起中的消费任务，验证关闭期被 cancel 回收
        self.consumer_task: asyncio.Task[object] = asyncio.create_task(asyncio.sleep(3600))


async def test_assembly_success_cleans_up_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """装配成功 -> 关闭期 cancel 消费任务并关闭存档器。"""
    runtime = _FakeRuntime()

    async def _assemble(app: FastAPI) -> object:
        app.state.agent_engine = object()  # 断言引擎被挂到 app.state
        return runtime

    monkeypatch.setattr("app.main._assemble_agent_runtime", _assemble)

    await _run_lifespan()

    assert runtime.consumer_task.cancelled() is True, "消费任务必须在关闭期被 cancel"
    assert runtime.store.closed is True, "CheckpointStore 长存活连接必须关闭"
