"""Redis Stream 优先级队列客户端。

设计动机（对齐 doc 04 §6）：
- 按优先级分流 Redis Stream（P0-P3），高优先级任务优先消费
- 消费组机制保证 At-Least-Once 语义 + 崩溃恢复（stalled 消息重投）
- 重试与死信队列隔离，避免坏消息阻塞整个队列
- 任务幂等性检查，已终态任务不重复执行

核心机制：
- Stream 命名：tasks:stream:{P0|P1|P2|P3}，死信 tasks:deadletter
- 消费组：agent-workers，启动时自动创建（MKSTREAM）
- 消费顺序：P0 -> P3 轮询，高优先级非空则优先消费
- 重试上限：retry_count <= 2，超限移入死信
- stalled 恢复：XPENDING 检测超时未 ACK，XCLAIM 重新分配
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import get_session_factory
from app.repository.task import TaskRepository
from app.schema.task import TaskStatus

from .redis import get_redis_client

logger = logging.getLogger(__name__)

# ---------------- 常量定义 ----------------
STREAM_PREFIX = "tasks:stream"
STREAM_DEADLETTER = "tasks:deadletter"
CONSUMER_GROUP = "agent-workers"
PRIORITY_ORDER = ["P0", "P1", "P2", "P3"]  # 消费优先级（高 -> 低）
MAX_RETRY_COUNT = 2  # 对齐 tasks.max_retries = 2
STALLED_TIMEOUT_MS = 30 * 1000  # 30s 未 ACK 判定为 stalled
CONSUME_BLOCK_MS = 1000  # 单次 XREADGROUP 阻塞时长
# 幂等性检查用的终态集合（frozenset 一次性固定，避免每次调用重建 set）
_TERMINAL_STATUSES = frozenset({TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELED})


class QueueMessage:
    """队列消息结构体。

    与 Redis Stream 消息体一一对应，序列化/反序列化。
    所有字段与 TaskService 入参对齐，保证类型安全。
    """

    def __init__(
        self,
        task_id: str,  # DB 任务主键（int PK）序列化串；与 engine.run 的 str 形参一致
        task_type: str,
        thread_id: UUID,
        conversation_id: str | None,  # DB 会话主键（int PK）序列化串，常空
        priority: str,
        payload: dict[str, Any],
        retry_count: int = 0,
        enqueued_at: str | None = None,
        message_id: str | None = None,  # Redis Stream 消息 ID，消费时填充
        stream: str | None = None,     # 所属 Stream，消费时填充
    ) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.thread_id = thread_id
        self.conversation_id = conversation_id
        self.priority = priority
        self.payload = payload
        self.retry_count = retry_count
        self.enqueued_at = enqueued_at or datetime.now(UTC).isoformat()
        self.message_id = message_id  # type: ignore[assignment]  # 消费时赋值
        self.stream = stream  # type: ignore[assignment]  # 消费时赋值

    def to_dict(self) -> dict[str, Any]:
        """序列化为 Redis Stream 字段字典。"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "thread_id": str(self.thread_id),
            "conversation_id": self.conversation_id or "",
            "priority": self.priority,
            "payload": json.dumps(self.payload, ensure_ascii=False),
            "retry_count": str(self.retry_count),
            "enqueued_at": self.enqueued_at,
        }

    @classmethod
    def from_stream_entry(cls, stream: str, message_id: str, fields: dict[str, str]) -> QueueMessage:
        """从 Redis Stream 条目反序列化。"""
        return cls(
            task_id=fields["task_id"],
            task_type=fields["task_type"],
            thread_id=UUID(fields["thread_id"]),
            conversation_id=fields.get("conversation_id") or None,
            priority=fields["priority"],
            payload=json.loads(fields["payload"]),
            retry_count=int(fields.get("retry_count", "0")),
            enqueued_at=fields.get("enqueued_at"),
            message_id=message_id,
            stream=stream,
        )


class QueueClient:
    """Redis Stream 优先级队列客户端。

    职责：任务入队、消费确认、死信处理、stalled 恢复。

    用法：
        # 入队
        await queue.enqueue(message)

        # 消费（按优先级轮询）
        message = await queue.consume(consumer_name="worker-1")

        # 确认/重试/死信
        if success:
            await queue.ack(message)
        else:
            await queue.requeue_or_deadletter(message)
    """

    def __init__(
        self,
        redis: Redis | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._redis = redis or get_redis_client()
        # 对齐 WorkflowEngine 的注入模式：短会话 + 显式提交，测试可注入假工厂；
        # 修复旧实现在函数体内用「坏导入 + 同步迭代取异步 session」的错误用法
        # （app.core.db.get_db_session 不存在，且 next() 迭代 async session 在 async 世界必死）
        self._session_factory = session_factory or get_session_factory()
        self._consumer_name: str | None = None

    async def ensure_consumer_groups(self) -> None:
        """确保所有 Stream 的消费组已创建。

        启动时调用一次，保证 Stream 和消费组存在。
        使用 XGROUP CREATE MKSTREAM，Stream 不存在则自动创建。
        消费组已存在时 ResponseError 静默跳过，不抛异常。
        """
        streams = [f"{STREAM_PREFIX}:{p}" for p in PRIORITY_ORDER] + [STREAM_DEADLETTER]
        for stream in streams:
            try:
                await self._redis.xgroup_create(
                    name=stream,
                    groupname=CONSUMER_GROUP,
                    id="$",  # 从最新消息开始消费
                    mkstream=True,  # Stream 不存在则创建
                )
                logger.info("Created consumer group %s for stream %s", CONSUMER_GROUP, stream)
            except ResponseError as e:
                # BUSYGROUP Consumer Group name already exists 是正常情况
                if "BUSYGROUP" not in str(e):
                    logger.warning("Failed to create consumer group for %s: %s", stream, e)
            except Exception:
                logger.exception("Failed to ensure consumer group for %s", stream)

    async def enqueue(self, message: QueueMessage) -> str:
        """任务入队。

        根据 priority 自动路由到对应 Stream，返回 Redis 消息 ID。

        Args:
            message: 队列消息

        Returns:
            str: Redis Stream 消息 ID
        """
        stream = f"{STREAM_PREFIX}:{message.priority}"
        fields = message.to_dict()
        message_id = await self._redis.xadd(name=stream, fields=fields)  # type: ignore[arg-type]
        logger.info(
            "Task enqueued",
            extra={
                "task_id": str(message.task_id),
                "priority": message.priority,
                "stream": stream,
                "message_id": message_id,
            },
        )
        return message_id

    async def consume(self, consumer_name: str) -> QueueMessage | None:
        """按优先级消费一条消息。

        P0 -> P3 顺序轮询，找到第一条非空 Stream 消费。
        每条消息消费前检查任务是否已终态，已终态则直接 ACK 并继续。

        Args:
            consumer_name: 消费者名（如 worker-1、worker-2）

        Returns:
            QueueMessage | None: 消息体，无消息时返回 None
        """
        self._consumer_name = consumer_name

        for priority in PRIORITY_ORDER:
            stream = f"{STREAM_PREFIX}:{priority}"
            try:
                # XREADGROUP: > 表示读取尚未交付给其他消费者的消息
                result = await self._redis.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=consumer_name,
                    streams={stream: ">"},
                    count=1,
                    block=CONSUME_BLOCK_MS,
                )
            except Exception:
                logger.exception("Failed to read from stream %s", stream)
                continue

            if not result:
                    continue

            # result 格式: [(stream_name, [(message_id, fields)])]
            _, messages = result[0]
            if not messages:
                continue

            message_id, fields = messages[0]
            message = QueueMessage.from_stream_entry(
                stream=stream,
                message_id=message_id,
                fields=fields,  # type: ignore[arg-type]
            )

            # ---------------- 幂等性检查：任务已终态则直接 ACK，不执行
            if await self._is_task_terminal(message.task_id):
                logger.info(
                    "Task already terminal, ack directly",
                    extra={"task_id": str(message.task_id), "message_id": message_id},
                )
                await self.ack(message)
                continue

            logger.info(
                "Task consumed",
                extra={
                    "task_id": str(message.task_id),
                    "priority": priority,
                    "consumer": consumer_name,
                    "message_id": message_id,
                },
            )
            return message

        return None

    async def ack(self, message: QueueMessage) -> None:
        """确认消息消费成功。

        XACK 从 pending list 移除消息，避免重复消费。

        Args:
            message: 已消费的消息
        """
        if not message.stream or not message.message_id:
            logger.warning("Cannot ack message: missing stream or message_id")
            return

        try:
            await self._redis.xack(
                name=message.stream,
                groupname=CONSUMER_GROUP,
                ids=[message.message_id],
            )
            logger.info(
                "Task acked",
                extra={"task_id": str(message.task_id), "message_id": message.message_id},
            )
        except Exception:
            logger.exception(
                "Failed to ack message",
                extra={"task_id": str(message.task_id), "message_id": message.message_id},
            )

    async def requeue_or_deadletter(self, message: QueueMessage) -> None:
        """消息重试或移入死信队列。

        retry_count < MAX_RETRY_COUNT：retry_count++ 后重新入队
        retry_count >= MAX_RETRY_COUNT：移入死信队列，不再重试

        Args:
            message: 消费失败的消息
        """
        message.retry_count += 1

        if message.retry_count < MAX_RETRY_COUNT:
            # 重试：重新入队（保留原优先级），原消息 XACK
            new_message = QueueMessage(
                task_id=message.task_id,
                task_type=message.task_type,
                thread_id=message.thread_id,
                conversation_id=message.conversation_id,
                priority=message.priority,
                payload=message.payload,
                retry_count=message.retry_count,
            )
            await self.enqueue(new_message)
            await self.ack(message)
            logger.warning(
                "Task requeued",
                extra={
                    "task_id": str(message.task_id),
                    "retry_count": message.retry_count,
                    "max_retries": MAX_RETRY_COUNT,
                },
            )
        else:
            # 死信：移入 deadletter stream，原消息 XACK
            try:
                await self._redis.xadd(
                    name=STREAM_DEADLETTER,
                    fields=message.to_dict(),  # type: ignore[arg-type]
                )
                await self.ack(message)
                logger.error(
                    "Task moved to deadletter",
                    extra={
                        "task_id": str(message.task_id),
                        "retry_count": message.retry_count,
                        "original_stream": message.stream,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to move task to deadletter",
                    extra={"task_id": str(message.task_id)},
                )

    async def recover_stalled(self, consumer_name: str) -> int:
        """恢复 stalled 消息（超时未 ACK）。

        XPENDING 检测所有超过 STALLED_TIMEOUT_MS 未 ACK 的消息，
        XCLAIM 转移给当前消费者，便于崩溃 Worker 的任务重新执行。

        Args:
            consumer_name: 当前消费者名

        Returns:
            int: 恢复的消息数量
        """
        recovered = 0
        min_idle_time = STALLED_TIMEOUT_MS

        for priority in PRIORITY_ORDER:
            stream = f"{STREAM_PREFIX}:{priority}"
            try:
                # XPENDING: 查 pending 消息概要
                pending_info = await self._redis.xpending(
                    name=stream,
                    groupname=CONSUMER_GROUP,
                )
                pending_count = pending_info["pending"]
                if pending_count == 0:
                    continue

                # XPENDING range: 获取具体 pending 消息列表
                pending_messages = await self._redis.xpending_range(
                    name=stream,
                    groupname=CONSUMER_GROUP,
                    min="-",
                    max="+",
                    count=pending_count,
                )

                for msg in pending_messages:
                    if msg["time_since_delivered"] < min_idle_time:
                        continue

                    # XCLAIM: 重新分配给当前消费者
                    claimed = await self._redis.xclaim(
                        name=stream,
                        groupname=CONSUMER_GROUP,
                        consumername=consumer_name,
                        min_idle_time=min_idle_time,
                        message_ids=[msg["message_id"]],
                        justid=True,
                    )

                    if claimed:
                        recovered += len(claimed)
                        logger.warning(
                            "Recovered stalled message",
                            extra={
                                "stream": stream,
                                "message_ids": claimed,
                                "original_consumer": msg["consumer_name"],
                                "idle_ms": msg["time_since_delivered"],
                            },
                        )
            except Exception:
                logger.exception("Failed to recover stalled messages from %s", stream)

        if recovered > 0:
            logger.info("Recovered %d stalled messages total", recovered)
        return recovered

    async def _is_task_terminal(self, task_id: str) -> bool:
        """检查任务是否已终态。

        幂等性保障：消息可能因重试重复投递，
        已终态任务直接 ACK 跳过，避免重复执行。

        终态：succeeded / failed / canceled
        """
        try:
            async with self._session_factory() as session:
                # get(id: int) 接收 DB 主键：task_id 是消息里的 int PK 序列化串
                task = await TaskRepository(session).get(int(task_id))
        except Exception:
            logger.exception("Failed to check task terminal status", extra={"task_id": task_id})
            return False  # 检查失败，保守假设非终态，继续执行
        if task is None:
            # 任务不存在，视为终态（避免死循环）
            return True
        return task.status in _TERMINAL_STATUSES


@lru_cache(maxsize=1)
def get_queue_client() -> QueueClient:
    """获取 QueueClient 单例。

    lru_cache 保证进程内仅一个实例，共享 Redis 连接池。
    启动时需手动调用 ensure_consumer_groups() 初始化 Stream 和消费组。
    """
    return QueueClient()
