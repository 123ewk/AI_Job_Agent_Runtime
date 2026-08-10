"""WebSocket 实时事件推送。

提供任务状态变更、HR 消息通知、审批请求等实时事件推送。
前端通过 WebSocket 连接后，自动订阅当前用户的所有事件。

事件类型（type）：
- task.updated: 任务状态变更（进度、结果、错误）
- task.step: Agent 执行节点更新（用于展示执行路径）
- message.received: HR 新消息到达
- approval.required: 需要人工确认
- sync.progress: 同步进度更新
- monitor.state: 监听状态变更
- log.appended: 关键日志追加

连接方式：
    ws://localhost:8000/ws/tasks/{task_id}?token=xxx

心跳：
    客户端每 30s 发送 {"type":"ping"}，服务端回复 {"type":"pong"}。
    60s 无心跳服务端主动断开。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger

ws_router = APIRouter(tags=["websocket"])
logger = get_logger("app.api.ws")


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


manager = ConnectionManager()


def _build_event(event_type: str, data: dict[str, Any], trace_id: str | None = None) -> dict[str, Any]:
    """构建标准事件消息格式。"""
    return {
        "type": event_type,
        "event_id": f"evt_{int(datetime.now(timezone.utc).timestamp())}_{id(data)}",
        "ts": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id or "",
        "data": data,
    }


@ws_router.websocket("/ws/tasks/{task_id}")
async def websocket_task_endpoint(websocket: WebSocket, task_id: int, token: str | None = None) -> None:
    """任务专属 WebSocket 端点。

    订阅单个任务的实时事件：状态变更、进度更新、日志追加等。

    消息格式::
        {
            "type": "task.updated",
            "event_id": "evt_xxx",
            "ts": "2024-01-01T00:00:00Z",
            "trace_id": "trace_xxx",
            "data": {
                "task_id": 123,
                "status": "running",
                "progress": 0.5,
                "message": "正在处理..."
            }
        }
    """
    # TODO: 验证 JWT token，提取 user_id
    user_id = 1  # 单用户模式

    await manager.connect(websocket, user_id=user_id, task_id=task_id)

    try:
        # 发送连接成功确认
        await websocket.send_json(
            _build_event(
                "system.connected",
                {"task_id": task_id, "status": "connected", "server_time": datetime.now(timezone.utc).isoformat()},
            )
        )

        # 消息循环
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                message = json.loads(data)

                # 心跳响应
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "ts": datetime.now(timezone.utc).isoformat()})

                # 客户端订阅其他任务
                elif message.get("type") == "subscribe":
                    sub_task_id = message.get("task_id")
                    if sub_task_id and sub_task_id != task_id:
                        logger.info(
                            "client_subscribe_additional",
                            extra={"task_id": task_id, "subscribe_to": sub_task_id},
                        )
                        # TODO: 支持多任务订阅

            except asyncio.TimeoutError:
                # 60s 未收到消息，主动断开
                logger.warning("websocket_heartbeat_timeout", extra={"task_id": task_id})
                break

    except WebSocketDisconnect:
        logger.info("websocket_client_disconnected", extra={"task_id": task_id})
    except Exception as exc:
        logger.exception("websocket_error", extra={"task_id": task_id, "error": str(exc)})
    finally:
        await manager.disconnect(websocket, user_id=user_id, task_id=task_id)


@ws_router.websocket("/ws/user")
async def websocket_user_endpoint(websocket: WebSocket, token: str | None = None) -> None:
    """用户级 WebSocket 端点。

    订阅当前用户的所有事件：任务、消息、审批、同步等。
    适合 Dashboard 全局实时通知。
    """
    # TODO: 验证 JWT token，提取 user_id
    user_id = 1  # 单用户模式

    await manager.connect(websocket, user_id=user_id, task_id=None)

    try:
        # 发送连接成功确认
        await websocket.send_json(
            _build_event(
                "system.connected",
                {"user_id": user_id, "status": "connected", "server_time": datetime.now(timezone.utc).isoformat()},
            )
        )

        # 消息循环
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                message = json.loads(data)

                # 心跳响应
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "ts": datetime.now(timezone.utc).isoformat()})

            except asyncio.TimeoutError:
                logger.warning("websocket_heartbeat_timeout", extra={"user_id": user_id})
                break

    except WebSocketDisconnect:
        logger.info("websocket_client_disconnected", extra={"user_id": user_id})
    except Exception as exc:
        logger.exception("websocket_error", extra={"user_id": user_id, "error": str(exc)})
    finally:
        await manager.disconnect(websocket, user_id=user_id, task_id=None)


# Service 层调用的事件发送接口
async def emit_task_updated(task_id: int, user_id: int, data: dict[str, Any]) -> None:
    """发送任务状态更新事件。"""
    message = _build_event("task.updated", data)
    await manager.send_to_task(task_id, message)
    await manager.send_to_user(user_id, message)


async def emit_task_step(task_id: int, user_id: int, node: str, state: str, detail: str | None = None) -> None:
    """发送 Agent 执行节点更新事件。"""
    message = _build_event(
        "task.step",
        {"task_id": task_id, "node": node, "state": state, "detail": detail},
    )
    await manager.send_to_task(task_id, message)
    await manager.send_to_user(user_id, message)


async def emit_approval_required(approval_id: int, task_id: int, user_id: int, expires_at: str) -> None:
    """发送人工确认请求事件。"""
    message = _build_event(
        "approval.required",
        {"approval_id": approval_id, "task_id": task_id, "expires_at": expires_at},
    )
    await manager.send_to_task(task_id, message)
    await manager.send_to_user(user_id, message)


async def emit_message_received(conversation_id: int, user_id: int, message: dict[str, Any]) -> None:
    """发送 HR 新消息到达事件。"""
    data = {"conversation_id": conversation_id, "message": message}
    message_obj = _build_event("message.received", data)
    await manager.send_to_user(user_id, message_obj)


async def emit_sync_progress(user_id: int, sync_record_id: int, synced: int, total: int) -> None:
    """发送同步进度更新事件。"""
    message = _build_event(
        "sync.progress",
        {"sync_record_id": sync_record_id, "synced": synced, "total": total, "progress": synced / total if total > 0 else 0},
    )
    await manager.send_to_user(user_id, message)


async def emit_log_appended(task_id: int, user_id: int, level: str, node: str, msg: str) -> None:
    """发送关键日志追加事件。"""
    message = _build_event("log.appended", {"task_id": task_id, "level": level, "node": node, "message": msg})
    await manager.send_to_task(task_id, message)
    await manager.send_to_user(user_id, message)
