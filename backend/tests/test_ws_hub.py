"""ws_hub 事件发布单测（doc 12）。

不连真实 WebSocket：FakeWS 脚本化 send_json/accept，验证
- 注册后 emit 到达对应 task / user 连接且消息格式正确；
- 无订阅者时 emit 为静默 no-op（不抛、不阻塞）；
- 订阅者计数供日志排查。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.runtime.ws_hub import (
    ConnectionManager,
    _build_event,
    emit_approval_required,
    emit_message_received,
    emit_sync_progress,
    emit_task_step,
    emit_task_updated,
    manager,
)


class FakeWS:
    """脚本化 WebSocket：记录已发送消息，accept 空实现。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def accept(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _clean_hub() -> None:
    """每个用例前清空全局 manager 注册表，避免用例间互相污染。"""
    manager.active_connections.clear()
    manager.user_connections.clear()
    yield


def _noop() -> None:
    """占位空函数，避免文件顶部 import 出现未使用告警。"""


async def test_emit_task_updated_reaches_task_and_user() -> None:
    ws = FakeWS()
    await manager.connect(ws, user_id=1, task_id=7)

    await emit_task_updated(7, 1, {"status": "running", "message": "开始执行"})

    assert len(ws.sent) == 1
    event = ws.sent[0]
    assert event["type"] == "task.updated"
    assert event["data"]["status"] == "running"
    assert event["ts"]
    assert event["event_id"]


async def test_emit_attaches_standard_event_metadata() -> None:
    ws = FakeWS()
    await manager.connect(ws, user_id=1, task_id=7)

    await emit_task_step(7, 1, "planner", "running")

    event = ws.sent[0]
    # 事件信封三要素：type / ts / event_id（trace_id 可空）
    assert event["type"] == "task.step"
    assert {"ts", "event_id", "data"} <= set(event)
    assert event["data"]["node"] == "planner"
    assert event["data"]["state"] == "running"


async def test_emit_without_subscribers_is_noop() -> None:
    # 无任何连接：emit 不该抛，也不该产生副作用
    await emit_task_updated(7, 1, {"status": "running"})


async def test_emit_only_to_matching_task() -> None:
    ws_other = FakeWS()
    await manager.connect(ws_other, user_id=2, task_id=99)
    ws_target = FakeWS()
    await manager.connect(ws_target, user_id=1, task_id=7)

    await emit_task_updated(7, 1, {"status": "succeeded"})

    assert ws_target.sent, "目标任务应收到事件"
    assert ws_other.sent == [], "其它任务/其它用户的连接不应收到"


async def test_emit_approval_required_carries_expiry() -> None:
    ws = FakeWS()
    await manager.connect(ws, user_id=1, task_id=7)

    await emit_approval_required(101, 7, 1, "2026-01-01T00:00:00Z")

    assert ws.sent[0]["type"] == "approval.required"
    assert ws.sent[0]["data"]["approval_id"] == 101
    assert ws.sent[0]["data"]["expires_at"] == "2026-01-01T00:00:00Z"


async def test_user_only_events_skip_task_channel() -> None:
    """message.received / sync.progress 走用户通道；无 task 连接也投递。"""
    ws = FakeWS()
    await manager.connect(ws, user_id=1, task_id=None)

    await emit_message_received(5, 1, {"text": "你好"})
    await emit_sync_progress(1, 9, 2, 10)

    types = [e["type"] for e in ws.sent]
    assert types == ["message.received", "sync.progress"]
    assert ws.sent[1]["data"]["progress"] == pytest.approx(0.2)


async def test_subscriber_count_reflects_registrations() -> None:
    ws_task = FakeWS()
    await manager.connect(ws_task, user_id=1, task_id=7)

    # 任务订阅 => task 通道 1 个连接；用户通道在 task 连接下 user=1 也应计数
    assert manager.subscriber_count(task_id=7, user_id=1) == 2
    assert manager.subscriber_count(task_id=7) == 1


async def test_build_event_shape() -> None:
    event = _build_event("system.connected", {"task_id": 7})
    assert event["type"] == "system.connected"
    assert event["data"] == {"task_id": 7}
    assert "ts" in event


async def test_manager_disconnect_cleans_up() -> None:
    ws = FakeWS()
    await manager.connect(ws, user_id=1, task_id=7)
    assert manager.subscriber_count(task_id=7) == 1

    await manager.disconnect(ws, user_id=1, task_id=7)

    assert manager.subscriber_count(task_id=7) == 0
    assert manager.subscriber_count(user_id=1) == 0


async def test_connection_manager_standalone() -> None:
    """独立 ConnectionManager 实例可与全局 manager 并存（不共享状态）。"""
    ws = FakeWS()
    cm = ConnectionManager()
    await cm.connect(ws, user_id=2, task_id=1)
    assert manager.subscriber_count(user_id=2) == 0  # 全局 manager 不受影响
    await cm.disconnect(ws, user_id=2, task_id=1)
