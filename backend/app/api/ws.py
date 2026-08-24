"""WebSocket 实时事件推送（doc 12）——只保留路由层职责。

连接注册与事件广播能力在 ``app/agent/runtime/ws_hub.py``（动作源所在层持有单例
manager，编排层同层 emit 不失配），本文件是唯一接线点：
- ``/ws/tasks/{task_id}``：任务专属订阅（task.updated / task.step / approval.required / log.appended）
- ``/ws/user``：用户级全局订阅（所有事件）

连接方式：ws://localhost:8000/ws/tasks/{task_id}?token=xxx
心跳：客户端每 30s 发送 {"type":"ping"}，服务端回复 {"type":"pong"}；60s 无心跳断开。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agent.runtime.ws_hub import _build_event, manager
from app.core.logging import get_logger

ws_router = APIRouter(tags=["websocket"])
logger = get_logger("app.api.ws")


@ws_router.websocket("/ws/tasks/{task_id}")
async def websocket_task_endpoint(websocket: WebSocket, task_id: int, token: str | None = None) -> None:  # noqa: ARG001
    """任务专属 WebSocket 端点。

    订阅单个任务的实时事件：状态变更、节点进度、审批、日志追加等。

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
                {"task_id": task_id, "status": "connected", "server_time": datetime.now(UTC).isoformat()},
            )
        )

        # 消息循环
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                message = json.loads(data)

                # 心跳响应
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "ts": datetime.now(UTC).isoformat()})

                # 客户端订阅其他任务
                elif message.get("type") == "subscribe":
                    sub_task_id = message.get("task_id")
                    if sub_task_id and sub_task_id != task_id:
                        logger.info(
                            "client_subscribe_additional",
                            extra={"task_id": task_id, "subscribe_to": sub_task_id},
                        )
                        # TODO: 支持多任务订阅

            except TimeoutError:
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
async def websocket_user_endpoint(websocket: WebSocket, token: str | None = None) -> None:  # noqa: ARG001
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
                {"user_id": user_id, "status": "connected", "server_time": datetime.now(UTC).isoformat()},
            )
        )

        # 消息循环
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                message = json.loads(data)

                # 心跳响应
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "ts": datetime.now(UTC).isoformat()})

            except TimeoutError:
                logger.warning("websocket_heartbeat_timeout", extra={"user_id": user_id})
                break

    except WebSocketDisconnect:
        logger.info("websocket_client_disconnected", extra={"user_id": user_id})
    except Exception as exc:
        logger.exception("websocket_error", extra={"user_id": user_id, "error": str(exc)})
    finally:
        await manager.disconnect(websocket, user_id=user_id, task_id=None)
