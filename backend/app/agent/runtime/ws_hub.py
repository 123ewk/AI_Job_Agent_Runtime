"""WebSocket 事件发布 hub（doc 12：动作源所在层持有广播能力）。

把 ConnectionManager 单例与 emit_*（task.updated / task.step / approval.required /
message.received / sync.progress / log.appended）从 ``app/api/ws.py`` 抽至此。

**为什么搬**：事件产生方（graph 节点 / WorkflowEngine / QueueConsumer）都在 ``app/agent/``
编排层。若留在 ``app/api/ws.py``，编排层直接 import 会形成 ``agent -> api`` 反向依赖
（路由层不得被业务/编排层依赖）。放本层后：编排层 import 本模块 = 同层合法、无环；
``api/ws.py`` 只注册连接（import 本模块）。

**日志即排查手段**：每个 emit 记一条结构化 INFO（event_type / task_id / user_id /
subscribers），send 失败由 ``send_to_*`` 记 WARNING。定位"事件没到"时先看是否有
``ws_event_emit`` 日志（事件是否发出）再对照 subscribers（是否没人订阅）。

无订阅连接时 emit 为静默 no-op（不抛、不阻塞），保证事件广播永不拖垮业务执行。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from starlette.websockets import WebSocket

from app.core.logging import get_logger

logger = get_logger("app.agent.runtime.ws_hub")


class ConnectionManager:
    """连接管理器。

    维护活跃的 WebSocket 连接，支持按用户、按任务广播消息。
    """

    def __init__(self) -> None:
        # task_id -> list[WebSocket]
        self.active_connections: dict[int, list[WebSocket]] = {}
        # user_id -> list[WebSocket]
        self.user_connections: dict[int, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: int, task_id: int | None = None) -> None:
        """接受新连接并注册。"""
        await websocket.accept()
        async with self._lock:
            if task_id is not None:
                if task_id not in self.active_connections:
                    self.active_connections[task_id] = []
                self.active_connections[task_id].append(websocket)

            if user_id not in self.user_connections:
                self.user_connections[user_id] = []
            self.user_connections[user_id].append(websocket)

        logger.info(
            "websocket_connected",
            extra={"user_id": user_id, "task_id": task_id, "active_count": len(self.user_connections.get(user_id, []))},
        )

    async def disconnect(self, websocket: WebSocket, user_id: int, task_id: int | None = None) -> None:
        """连接断开时清理注册信息。"""
        async with self._lock:
            if task_id is not None and task_id in self.active_connections:
                if websocket in self.active_connections[task_id]:
                    self.active_connections[task_id].remove(websocket)
                if not self.active_connections[task_id]:
                    del self.active_connections[task_id]

            if user_id in self.user_connections:
                if websocket in self.user_connections[user_id]:
                    self.user_connections[user_id].remove(websocket)
                if not self.user_connections[user_id]:
                    del self.user_connections[user_id]

        logger.info(
            "websocket_disconnected",
            extra={"user_id": user_id, "task_id": task_id},
        )

    def subscriber_count(self, task_id: int | None = None, user_id: int | None = None) -> int:
        """当前订阅者连接数（供 emit 日志确认事件有没有人接）。

        事件同时按 task 与 user 两类通道分发；取"任务订阅去重 + 用户订阅去重"的连接
        数，None 表示该通道不纳入查询。asyncio 单线程：同一协程内同步读 dict 不会被
        并发写中断（connect/disconnect 都在同一 event loop 串行执行）。
        """
        task_count = len(
            {id(c) for c in self.active_connections.get(task_id or 0, [])}
        ) if task_id is not None else 0
        user_count = len(
            {id(c) for c in self.user_connections.get(user_id or 0, [])}
        ) if user_id is not None else 0
        return task_count + user_count


    async def send_to_task(self, task_id: int, message: dict[str, Any]) -> None:
        """给指定任务的所有连接发送消息。"""
        if task_id not in self.active_connections:
            return

        for connection in self.active_connections[task_id]:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.warning(
                    "websocket_send_failed",
                    extra={"task_id": task_id, "error": str(exc)},
                )

    async def send_to_user(self, user_id: int, message: dict[str, Any]) -> None:
        """给指定用户的所有连接发送消息。"""
        if user_id not in self.user_connections:
            return

        for connection in self.user_connections[user_id]:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.warning(
                    "websocket_send_failed",
                    extra={"user_id": user_id, "error": str(exc)},
                )

    async def broadcast(self, message: dict[str, Any]) -> None:
        """广播给所有连接。"""
        for connections in self.active_connections.values():
            for connection in connections:
                try:
                    await connection.send_json(message)
                except Exception as exc:
                    logger.warning("websocket_broadcast_failed", extra={"error": str(exc)})

    async def send_to_subscribers(self, task_id: int, user_id: int, message: dict[str, Any]) -> None:
        """按 task + user 两个通道去重广播，保证每个连接只收到一次。

        同一连接可能同时注册在 task 端点（task+user 两个 dict）与 user 端点——
        简单 ``send_to_task + send_to_user`` 会让它收到**两遍**。按连接对象 id 去重
        后统一发送：覆盖范围 = 任务订阅 ∪ 用户订阅，杜绝重复。
        """
        task_conns = list(self.active_connections.get(task_id, []))
        user_conns = list(self.user_connections.get(user_id, []))
        seen: dict[int, WebSocket] = {}
        for conn in task_conns + user_conns:
            seen.setdefault(id(conn), conn)
        for conn in seen.values():
            try:
                await conn.send_json(message)
            except Exception as exc:
                logger.warning(
                    "websocket_send_failed",
                    extra={"task_id": task_id, "user_id": user_id, "error": str(exc)},
                )


manager = ConnectionManager()


def _build_event(event_type: str, data: dict[str, Any], trace_id: str | None = None) -> dict[str, Any]:
    """构建标准事件消息格式。"""
    return {
        "type": event_type,
        "event_id": f"evt_{int(datetime.now(UTC).timestamp())}_{id(data)}",
        "ts": datetime.now(UTC).isoformat(),
        "trace_id": trace_id or "",
        "data": data,
    }


async def _emit(
    event_type: str,
    data: dict[str, Any],
    *,
    task_id: int,
    user_id: int,
    to_task: bool = True,
) -> None:
    """统一广播 + 记录事件日志（subscriber 计数供排查）。"""
    subs = manager.subscriber_count(task_id=task_id, user_id=user_id)
    logger.info(
        "ws_event_emit",
        extra={
            "event_type": event_type,
            "task_id": task_id,
            "user_id": user_id,
            "subscribers": subs,
        },
    )
    message = _build_event(event_type, data)
    if to_task:
        await manager.send_to_subscribers(task_id, user_id, message)
    else:
        await manager.send_to_user(user_id, message)


# ---------------------------------------------------------------------------
# Service / 编排层调用的事件发送接口
# ---------------------------------------------------------------------------
async def emit_task_updated(task_id: int, user_id: int, data: dict[str, Any]) -> None:
    """发送任务状态变更事件（running / waiting_approval / succeeded / failed）。"""
    await _emit("task.updated", data, task_id=task_id, user_id=user_id)


async def emit_notification(
    user_id: int,
    level: str,
    title: str,
    message: str,
) -> None:
    """发送弹窗提醒事件（走用户通道，非任务维度）。

    供「LLM 未配置」等需要打断用户、引导去设置页的场景使用；前端收到后据 level
    渲染提示框。语义与 task.updated 分离：notification 是面向用户的主动提醒，
    与具体任务状态解耦。
    """
    await _emit(
        "notification",
        {"level": level, "title": title, "message": message},
        task_id=0,
        user_id=user_id,
        to_task=False,
    )


async def emit_task_step(task_id: int, user_id: int, node: str, state: str, detail: str | None = None) -> None:
    """发送 Agent 执行节点更新事件（node 级执行路径）。"""
    await _emit(
        "task.step",
        {"task_id": task_id, "node": node, "state": state, "detail": detail},
        task_id=task_id,
        user_id=user_id,
    )


async def emit_approval_required(approval_id: int, task_id: int, user_id: int, expires_at: str) -> None:
    """发送人工确认请求事件。"""
    await _emit(
        "approval.required",
        {"approval_id": approval_id, "task_id": task_id, "expires_at": expires_at},
        task_id=task_id,
        user_id=user_id,
    )


async def emit_message_received(conversation_id: int, user_id: int, message_obj: dict[str, Any]) -> None:
    """发送 HR 新消息到达事件。"""
    await _emit(
        "message.received",
        {"conversation_id": conversation_id, "message": message_obj},
        task_id=0,  # message 事件无单一任务维度；HR 消息通道归属用户
        user_id=user_id,
        to_task=False,
    )


async def emit_sync_progress(user_id: int, sync_record_id: int, synced: int, total: int) -> None:
    """发送同步进度更新事件。"""
    await _emit(
        "sync.progress",
        {
            "sync_record_id": sync_record_id,
            "synced": synced,
            "total": total,
            "progress": synced / total if total > 0 else 0,
        },
        task_id=0,
        user_id=user_id,
        to_task=False,
    )


async def emit_log_appended(task_id: int, user_id: int, level: str, node: str, msg: str) -> None:
    """发送关键日志追加事件。"""
    await _emit(
        "log.appended",
        {"task_id": task_id, "level": level, "node": node, "message": msg},
        task_id=task_id,
        user_id=user_id,
    )


__all__ = [
    "ConnectionManager",
    "_build_event",
    "emit_approval_required",
    "emit_log_appended",
    "emit_message_received",
    "emit_notification",
    "emit_sync_progress",
    "emit_task_step",
    "emit_task_updated",
    "manager",
]
