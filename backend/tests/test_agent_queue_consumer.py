"""QueueConsumer 单元测试 + QueueMessage 序列化回归（不连 Redis/DB）。

覆盖两块：
1. QueueMessage round-trip：锁住「task_id/conversation_id 是 int 主键序列化串，
   而非 UUID」的修复——消费端不得 UUID() 解析 int PK（否则 ValueError）。
2. QueueConsumer 消费语义三态分流：
   - run 正常返回（终态/挂起）-> ACK（挂起也必须 ACK，防 stalled 重投触发重复 run）
   - 执行锁忙（LockTimeoutError）-> 不动消息（留给 stalled 重投，不耗 retry_count）
   - 其他异常 -> requeue_or_deadletter
   - NotFoundError（任务已被删）-> ACK 丢弃

假队列复用项目"每测试注入边界对象"风格：内存记录 ack/requeue 调用，不需 Redis。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agent.runtime.lock_manager import LockTimeoutError
from app.agent.runtime.queue_consumer import QueueConsumer
from app.infra.queue import QueueMessage


# ----------------------------------------------------------------------
# 假边界对象
# ----------------------------------------------------------------------
@dataclass
class _FakeQueue:
    """内存假队列：consume 返回预设消息，记录 ack/requeue 调用。

    recover_stalled 返回 0（不真正恢复）；consume 按设定序列逐个返回。
    """

    messages: list[QueueMessage] = field(default_factory=list)
    acked: list[str] = field(default_factory=list)
    requeued: list[str] = field(default_factory=list)
    recover_called: bool = False

    async def recover_stalled(self, _consumer_name: str) -> int:
        self.recover_called = True
        return 0

    async def consume(self, _consumer_name: str) -> QueueMessage | None:
        if not self.messages:
            return None
        return self.messages.pop(0)

    async def ack(self, message: QueueMessage) -> None:
        self.acked.append(message.task_id)

    async def requeue_or_deadletter(self, message: QueueMessage) -> None:
        self.requeued.append(message.task_id)


class _FakeEngine:
    """假引擎：按预设 result/exception 控制 run()"""

    def __init__(self, result: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        self._result = result or {}
        self._exc = exc
        self.run_calls: list[str] = []

    async def run(self, task_id: str) -> dict[str, Any]:
        self.run_calls.append(task_id)
        if self._exc is not None:
            raise self._exc
        return self._result


def _msg(task_id: str = "123") -> QueueMessage:
    """构造一条与 TaskService 入队格式一致的假消息（task_id 为 int PK 串）。"""
    return QueueMessage(
        task_id=task_id,
        task_type="chat",
        thread_id=uuid.uuid4(),
        conversation_id="5",
        priority="P0",
        payload={"text": "hi"},
    )


# ----------------------------------------------------------------------
# QueueMessage round-trip（回归修复：int 主键串不得被 UUID() 解析）
# ----------------------------------------------------------------------
def test_task_message_round_trip_preserves_int_pk_string() -> None:
    """to_dict -> from_stream_entry 双向不丢字段，且不触发 UUID 解析崩溃。"""
    original = _msg(task_id="123")
    fields = original.to_dict()
    # task_id 是 int 主键串，不是 UUID：若消费端 UUID(fields["task_id"]) 会抛 ValueError
    parsed = QueueMessage.from_stream_entry(stream="tasks:stream:P0", message_id="1-0", fields=fields)

    assert parsed.task_id == "123"          # 不丢失、不解析成 UUID 失败
    assert parsed.conversation_id == "5"    # conversation_id 同样保持字符串
    assert parsed.priority == "P0"
    assert parsed.payload == {"text": "hi"}
    assert parsed.thread_id == original.thread_id
    assert parsed.message_id == "1-0"
    assert parsed.stream == "tasks:stream:P0"


def test_task_message_round_trip_allows_empty_conversation() -> None:
    """conversation_id 为空时 round-trip 保持 None（非空串）。"""
    msg = QueueMessage(
        task_id="9",
        task_type="job",
        thread_id=uuid.uuid4(),
        conversation_id=None,
        priority="P1",
        payload={},
    )
    parsed = QueueMessage.from_stream_entry(
        stream="tasks:stream:P1", message_id="2-0", fields=msg.to_dict()
    )
    assert parsed.conversation_id is None


# ----------------------------------------------------------------------
# QueueConsumer 消费语义
# ----------------------------------------------------------------------
def test_consume_once_empty_queue_returns_0_and_recovers_stalled() -> None:
    queue = _FakeQueue()
    engine = _FakeEngine()
    consumer = QueueConsumer(engine=engine, queue=queue)  # type: ignore[arg-type]

    count = asyncio.run(consumer.consume_once())

    assert count == 0
    assert queue.recover_called is True


def test_terminal_result_acks_message() -> None:
    queue = _FakeQueue(messages=[_msg("1")])
    engine = _FakeEngine(result={"terminal": "succeeded"})
    consumer = QueueConsumer(engine=engine, queue=queue)  # type: ignore[arg-type]

    async def go() -> None:
        assert await consumer.consume_once() == 1
        assert engine.run_calls == ["1"]
        assert queue.acked == ["1"]
        assert queue.requeued == []

    asyncio.run(go())


def test_suspend_interrupt_is_acked() -> None:
    """挂起（含 __interrupt__）也必须 ACK：任务已落 WAITING_APPROVAL 且执行锁
    由引擎持有，走 Approval resume 续跑，不依赖队列重投。"""
    queue = _FakeQueue(messages=[_msg("2")])
    engine = _FakeEngine(result={"__interrupt__": [{}], "terminal": None})
    consumer = QueueConsumer(engine=engine, queue=queue)  # type: ignore[arg-type]

    async def go() -> None:
        assert await consumer.consume_once() == 1
        assert queue.acked == ["2"]
        assert queue.requeued == []

    asyncio.run(go())


def test_lock_busy_leaves_message_pending_unacked() -> None:
    """执行锁忙不 ack 也不 requeue（避免为"忙"误耗 retry_count 径入死信）。"""
    queue = _FakeQueue(messages=[_msg("3")])
    engine = _FakeEngine(exc=LockTimeoutError("execution lock busy"))
    consumer = QueueConsumer(engine=engine, queue=queue)  # type: ignore[arg-type]

    async def go() -> None:
        assert await consumer.consume_once() == 1
        assert engine.run_calls == ["3"]
        assert queue.acked == []
        assert queue.requeued == []

    asyncio.run(go())


def test_task_deleted_after_enqueue_is_acked_dropped() -> None:
    """任务删除后 NotFoundError：ACK 丢弃，不为不存在任务消耗重试/死信。"""
    from app.core.exceptions import NotFoundError

    queue = _FakeQueue(messages=[_msg("4")])
    engine = _FakeEngine(exc=NotFoundError("Task 4 not found"))
    consumer = QueueConsumer(engine=engine, queue=queue)  # type: ignore[arg-type]

    async def go() -> None:
        assert await consumer.consume_once() == 1
        assert queue.acked == ["4"]
        assert queue.requeued == []

    asyncio.run(go())


def test_other_exception_requeues_or_deadletters() -> None:
    queue = _FakeQueue(messages=[_msg("5")])
    engine = _FakeEngine(exc=RuntimeError("graph exploded"))
    consumer = QueueConsumer(engine=engine, queue=queue)  # type: ignore[arg-type]

    async def go() -> None:
        assert await consumer.consume_once() == 1
        assert engine.run_calls == ["5"]
        assert queue.acked == []
        assert queue.requeued == ["5"]

    asyncio.run(go())


def test_run_forever_processes_until_empty_then_stops_on_event() -> None:
    queue = _FakeQueue(messages=[_msg("1"), _msg("2")])
    engine = _FakeEngine(result={"terminal": "succeeded"})
    consumer = QueueConsumer(engine=engine, queue=queue)  # type: ignore[arg-type]
    stop = asyncio.Event()

    async def go() -> None:
        # 消费完 2 条 -> 队列空 -> consume 返回 None -> 置 stop_event 让循环退出
        await asyncio.sleep(0)  # 确保事件循环就绪
        task = asyncio.create_task(consumer.run_forever(idle_sleep=0.01, stop_event=stop))
        for _ in range(100):
            if len(engine.run_calls) == 2:
                stop.set()
                break
            await asyncio.sleep(0.01)
        await task
        assert engine.run_calls == ["1", "2"]
        assert queue.acked == ["1", "2"]

    asyncio.run(go())
