"""ApprovalService._resume_task 接线测试（engine_registry -> 后台 dispatch）。

不连 DB/Redis：引擎经 registry 注入假实现，ApprovalService 用内存假 session
（_resume_task 不触碰 db，仅记录日志 + 从 registry 取引擎派发续跑）。

锁住两个分支：
1. **registry 有引擎** -> 后台任务派发 engine.resume_by_task(task_id, decision)。
2. **registry 空**（引擎未装配）-> 优雅跳过，不抛错、不占用执行。

注：_resume_task 是私有方法；本测试直接调用以归零到「审批决策恢复」这一接线点，
避免走 approve() 的完整 @transactional + DB 校验路径（那属集成测试）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.agent.runtime.engine_registry import clear_runtime_engine, set_runtime_engine
from app.service.approval import ApprovalService


class _FakeEngine:
    """脚本化引擎：记录 resume_by_task 调用并置事件，供测试等待后台任务完成。"""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []
        self.resumed = asyncio.Event()

    async def resume_by_task(self, task_id: int, decision: str) -> dict[str, object]:
        self.calls.append((task_id, decision))
        self.resumed.set()
        return {}


def _service() -> ApprovalService:
    # _resume_task 不触碰 db：传一个空壳 AsyncSession 替身即可（repo 仅持有不做 I/O）
    return ApprovalService(db=SimpleNamespace())  # type: ignore[arg-type]


async def test_resume_dispatches_via_registry_engine() -> None:
    """registry 有引擎 -> _resume_task 后台派发 resume_by_task，参数正确。"""
    clear_runtime_engine()
    fake_engine = _FakeEngine()
    set_runtime_engine(fake_engine)  # type: ignore[arg-type]
    try:
        service = _service()
        await service._resume_task(task_id=7, approval_id=1, decision="approve")

        # 派发是后台任务：等事件确认它跑完，再断言
        await asyncio.wait_for(fake_engine.resumed.wait(), timeout=5)
        assert fake_engine.calls == [(7, "approve")]
    finally:
        clear_runtime_engine()


async def test_resume_with_no_engine_skips_gracefully() -> None:
    """registry 空（引擎未装配/已关闭）-> 优雅跳过，不抛错。"""
    clear_runtime_engine()
    service = _service()

    await service._resume_task(task_id=7, approval_id=1, decision="approve")  # 不应上抛


async def test_resume_dispatches_deny_decision() -> None:
    """决策透传：deny 也走后派发，参数含对应 decision。"""
    clear_runtime_engine()
    fake_engine = _FakeEngine()
    set_runtime_engine(fake_engine)  # type: ignore[arg-type]
    try:
        service = _service()
        await service._resume_task(task_id=9, approval_id=2, decision="deny")

        await asyncio.wait_for(fake_engine.resumed.wait(), timeout=5)
        assert fake_engine.calls == [(9, "deny")]
    finally:
        clear_runtime_engine()
