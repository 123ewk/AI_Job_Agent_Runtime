"""Queue 消费者（doc 04 §6）：取任务 -> WorkflowEngine.run -> ACK / 重试 / 死信。

职责单一：从优先级队列取任务，交给 WorkflowEngine 执行到终态或挂起，再按结果
确认（ACK）/ 重试入队（retry_count++）/ 移入死信。

消费语义（三态分流）：
1. **终态 / 挂起**（run 正常返回）——ACK。挂起（result 含 ``__interrupt__``）
   是**必须 ACK** 的关键点：任务已落到 WAITING_APPROVAL，执行锁由引擎持有，
   后续靠 Approval 决策经**同一引擎实例** resume() 续跑，**不依赖队列重投**；
   若不 ACK，30s 后 stalled 恢复会重投同一消息，导致对已挂起任务再次 run ->
   LockTimeoutError。
2. **执行锁忙**（LockTimeoutError）——**不动消息**。V1 单一执行锁，锁忙只可能
   发生在「已有任务挂起等审批」时，让其留在 pending，等 stalled 超时后
   XCLAIM 重投即可，不消耗 retry_count（不是执行失败）。
3. **其他异常**——requeue_or_deadletter（retry_count++，超 MAX_RETRY_COUNT
   移入死信）。

V1 严格单任务（doc 04 §8.1）：本类面向单 worker 进程内的单消费循环，进程内
至多一个 consumer 实例在跑。多 Worker 扩容是 V2+（Redis 分布式锁 + 多 consumer）。

依赖注入（对齐 WorkflowEngine/CheckpointStore 风格，均可单测）：
- ``engine``：WorkflowEngine 实例（持有执行锁与挂起态，必须进程内单例）。
- ``queue``：默认全局 QueueClient 单例；测试传 mock 队列，无需真 Redis。
"""

from __future__ import annotations

import asyncio
import logging

from app.agent.runtime.lock_manager import LockTimeoutError
from app.agent.runtime.workflow_engine import WorkflowEngine
from app.core.exceptions import NotFoundError
from app.infra.queue import QueueClient, QueueMessage, get_queue_client

logger = logging.getLogger(__name__)

# 挂起标记：LangGraph Interrupt 后 result 携带该键（doc 06 §8.2）
_INTERRUPT_KEY = "__interrupt__"


class QueueConsumer:
    """单任务消费循环（doc 04 §6.3）。"""

    def __init__(
        self,
        engine: WorkflowEngine,
        *,
        queue: QueueClient | None = None,
        consumer_name: str = "worker-1",
    ) -> None:
        self._engine = engine
        self._queue = queue or get_queue_client()
        self._consumer_name = consumer_name

    async def consume_once(self) -> int:
        """执行一轮「恢复 stalled -> 取消息 -> 处理」，返回本次处理的消息数。

        Returns:
            0 = 队列空或全被跳过；1 = 消费并处理了一条。
        """
        await self._queue.recover_stalled(self._consumer_name)
        try:
            message = await self._queue.consume(self._consumer_name)
        except Exception:
            logger.exception("Failed to consume message from queue")
            return 0
        if message is None:
            return 0
        await self._process(message)
        return 1

    async def run_forever(
        self,
        *,
        idle_sleep: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """持续消费直到 stop_event 置位（供 FastAPI lifespan 后台任务调用）。

        队列空时 sleep 防空转烧 CPU；stop_event 为 None 时永续运行。
        """
        while stop_event is None or not stop_event.is_set():
            processed = await self.consume_once()
            if processed == 0 and idle_sleep > 0:
                await asyncio.sleep(idle_sleep)

    # ------------------------------------------------------------------
    # 私有
    # ------------------------------------------------------------------
    async def _process(self, message: QueueMessage) -> None:
        """执行一条消息并按结果分流（ACK / 重试死信 / 搁置 pending）。"""
        task_id = message.task_id
        try:
            result = await self._engine.run(task_id)
        except LockTimeoutError as exc:
            # 执行锁被挂起中的任务占用：不留 pending 由 stalled 重投，
            # 不 ACK、不 requeue（避免为"忙"误耗 retry_count 径入死信）
            logger.info(
                "Execution lock busy, leave message pending",
                extra={"task_id": task_id, "detail": str(exc)},
            )
            return
        except NotFoundError:
            # 任务在取到消息后已被删除：ACK 丢弃，别为不存在任务消耗重试/死信
            logger.warning("Task deleted after enqueue, ack-dropping message", extra={"task_id": task_id})
            await self._queue.ack(message)
            return
        except Exception:
            logger.exception("Task execution failed", extra={"task_id": task_id})
            await self._queue.requeue_or_deadletter(message)
            return

        if _INTERRUPT_KEY in result:
            # 挂起等审批：ACK。引擎已持挂起态 + 执行锁，取审批 resume 续跑，
            # 不依赖队列；重投反而触发对挂起任务的重复 run -> LockTimeout
            logger.info("Task suspended awaiting approval, acked", extra={"task_id": task_id})
        else:
            logger.info("Task reached terminal, acked", extra={"task_id": task_id})
        await self._queue.ack(message)
