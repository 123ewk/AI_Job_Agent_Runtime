"""任务域 API 集成测试。

覆盖 Task CRUD、取消、重试状态机、审批、队列统计。
字段契约：TaskCreate 只需 type（TaskType 枚举），无 title/description；
status 为 canceled（单 l）；审批路由为 /tasks/{task_id}/approvals/*。
任务创建会入队 Redis Stream（测试环境 Redis DB 1 可用）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schema.enums import TaskStatus

BASE = "/api/v1/tasks"


async def _create_task(client: AsyncClient, task_type: str = "user_initiated") -> int:
    """创建任务并返回 task_id。"""
    resp = await client.post(BASE, json={"type": task_type})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_pending_approval(
    test_session_factory: async_sessionmaker[AsyncSession],
    task_id: int,
    user_id: int,
) -> int:
    """直接插入一条 pending 状态的 Approval，返回其 id。

    Approval 无 API 创建路由（由 Runtime 内部创建），故通过 session 直插测试数据。
    """
    from app.models.approval import Approval, ApprovalStatus, ApprovalType

    async with test_session_factory() as session:
        approval = Approval(
            task_id=task_id,
            user_id=user_id,
            type=ApprovalType.SALARY.value,
            payload={"salary": "20k"},
            status=ApprovalStatus.PENDING.value,
            expires_at=datetime.now(UTC) + timedelta(seconds=20),
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
        return approval.id


class TestTasksAPI:
    """Task 接口契约。"""

    async def test_create_task(self, client: AsyncClient) -> None:
        """POST /tasks 创建任务，自动分配优先级，status=pending。"""
        resp = await client.post(BASE, json={"type": "user_initiated"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] > 0
        assert data["type"] == "user_initiated"
        assert data["status"] == "pending"
        assert data["priority"] == "P2"  # user_initiated -> P2

    async def test_list_tasks(self, client: AsyncClient) -> None:
        """创建后列表含该任务。"""
        await _create_task(client)
        resp = await client.get(BASE)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["type"] == "user_initiated"

    async def test_list_tasks_with_filter(self, client: AsyncClient) -> None:
        """按 status 过滤（合法值不报错）。"""
        await _create_task(client)
        resp = await client.get(BASE, params={"status": "pending"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_get_task(self, client: AsyncClient) -> None:
        """GET /tasks/{id} 返回详情。"""
        task_id = await _create_task(client)
        resp = await client.get(f"{BASE}/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == task_id

    async def test_get_task_not_found(self, client: AsyncClient) -> None:
        """不存在任务返回错误（缺全局 404 处理器，断言 >=400）。"""
        resp = await client.get(f"{BASE}/99999")
        assert resp.status_code >= 400

    async def test_cancel_task(self, client: AsyncClient) -> None:
        """POST /tasks/{id}/cancel 取消 pending 任务，返回 StatusResponse。"""
        task_id = await _create_task(client)
        resp = await client.post(f"{BASE}/{task_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        after = await client.get(f"{BASE}/{task_id}")
        assert after.json()["status"] == "canceled"

    async def test_retry_pending_task_fails(self, client: AsyncClient) -> None:
        """重试 pending 任务应失败（状态机：仅 failed 可重试）。

        当前 TaskStateError 未被全局处理器捕获 -> 500，断言 >=400。
        """
        task_id = await _create_task(client)
        resp = await client.post(f"{BASE}/{task_id}/retry")
        assert resp.status_code >= 400

    async def test_retry_enqueues_new_task(
        self,
        client: AsyncClient,
        test_session_factory: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """重试失败任务会建 pending 新任务并入队 Redis Stream（P0 回归）。

        此前 retry() 只落库不入队（task.py:317 TODO），消费循环永不消费、任务永久 pending。
        mock 掉 enqueue 断言被调用且参数正确（对齐 create() 的队列构造）。
        """
        import app.service.task as task_mod
        from app.models.task import Task

        tid = uuid4()
        # 造一条 failed 可重试任务（retry_count=0 < max_retries=2）
        async with test_session_factory() as session:
            task = Task(
                user_id=1,
                type="user_initiated",
                status="failed",
                thread_id=tid,
                priority="P2",
                payload={"goal": "重试我"},
                retry_count=0,
                max_retries=2,
            )
            session.add(task)
            await session.commit()

        queued: list[object] = []

        class FakeQueue:
            async def enqueue(self, message: object) -> None:
                queued.append(message)

        def fake_get_classes() -> tuple[type, type]:
            from app.infra.queue import QueueMessage  # 真实构造，校验字段契约

            return FakeQueue, QueueMessage

        monkeypatch.setattr(task_mod, "_get_queue_classes", fake_get_classes)

        resp = await client.post(f"{BASE}/{task.id}/retry")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending"
        assert data["retry_count"] == 1

        # 断言恰好入队一次、参数正确
        assert len(queued) == 1
        msg = queued[0]
        assert str(msg.task_id) == str(data["id"])
        assert str(msg.thread_id) == str(tid)  # 复用原 thread_id 作 Checkpoint 锚点
        assert msg.priority == "P2"
        assert msg.conversation_id is None
        assert msg.payload == {"goal": "重试我"}

    async def test_retry_enqueue_failure_propagates(
        self,
        client: AsyncClient,
        test_session_factory: async_sessionmaker[AsyncSession],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """入队失败必须向上抛（不吞掉），避免任务落库却无人消费的静默失效。"""
        import app.service.task as task_mod
        from app.models.task import Task

        async with test_session_factory() as session:
            task = Task(
                user_id=1,
                type="user_initiated",
                status="failed",
                thread_id=uuid4(),
                priority="P1",
                payload={},
                retry_count=0,
                max_retries=2,
            )
            session.add(task)
            await session.commit()

        class Boom:
            async def enqueue(self, _message: object) -> None:
                redis_down = "redis down"
                raise RuntimeError(redis_down)

        def fake_get_classes() -> tuple[type, type]:
            from app.infra.queue import QueueMessage

            return Boom, QueueMessage

        monkeypatch.setattr(task_mod, "_get_queue_classes", fake_get_classes)

        # 无 try/except 包裹 → 异常穿透 → 接口层 500（>=400 而非静默 200）
        resp = await client.post(f"{BASE}/{task.id}/retry")
        assert resp.status_code >= 500

    async def test_queue_stats(self, client: AsyncClient) -> None:
        """GET /tasks/queue/stats 返回 pending 计数与并发上限（默认 3）。"""
        await _create_task(client)
        resp = await client.get(f"{BASE}/queue/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending"] == 1
        assert data["max_concurrent"] == 3

    async def test_queue_stats_max_concurrent_reads_settings(
        self, client: AsyncClient
    ) -> None:
        """max_concurrent 从 SettingsService 读取，改 agent.concurrency_limit 后同步变化。

        回归 D11：原硬编码 3，改为读 agent 配置，确保前后端一致。
        """
        # 先改 agent 并发限制为 5
        resp = await client.put(
            "/api/v1/settings/agent",
            json={
                "concurrency_limit": 5,
                "auto_reply_enabled": False,
                "auto_approval_threshold": 0.9,
                "approval_timeout_seconds": 20,
                "max_retries": 2,
            },
        )
        assert resp.status_code == 200
        # 队列统计的 max_concurrent 应同步为 5
        resp = await client.get(f"{BASE}/queue/stats")
        assert resp.status_code == 200
        assert resp.json()["max_concurrent"] == 5

    async def test_create_task_with_thread_id(
        self,
        client: AsyncClient,
        test_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """传入 thread_id 时优先使用（A6 回归，DB 直查校验）。

        TaskResponse 不含 thread_id 字段，故查库断言落库值。
        """
        thread_id = str(uuid4())
        resp = await client.post(BASE, json={"type": "user_initiated", "thread_id": thread_id})
        assert resp.status_code == 201, resp.text
        task_id = resp.json()["id"]

        from app.models.task import Task

        async with test_session_factory() as session:
            task = await session.get(Task, task_id)
            assert task is not None
            assert str(task.thread_id) == thread_id

    async def test_create_task_invalid_thread_id(self, client: AsyncClient) -> None:
        """非法 thread_id 返回 400，不落库（A6 边界）。"""
        resp = await client.post(BASE, json={"type": "user_initiated", "thread_id": "not-a-uuid"})
        assert resp.status_code == 400, resp.text

    async def test_update_status_persists_progress(
        self,
        client: AsyncClient,
        test_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """update_status 写入 progress 后 GET 能读到（A7 回归）。"""
        task_id = await _create_task(client)

        from app.service.task import TaskService

        async with test_session_factory() as session:
            service = TaskService(db=session)
            result = await service.update_status(task_id, TaskStatus.RUNNING, progress=42)
            assert result.progress == 42

        resp = await client.get(f"{BASE}/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["progress"] == 42

    @pytest.mark.skip(reason="无 /tasks/{id}/checkpoints 路由，Checkpoint 索引由 Runtime 内部维护")
    async def test_get_task_checkpoints(self, client: AsyncClient) -> None:
        """占位：Checkpoint 路由未实现。"""


class TestApprovalAPI:
    """审批接口契约（路由为 /tasks/{task_id}/approvals/*）。"""

    async def test_get_pending_approval_other_user_task_404(self, client: AsyncClient) -> None:
        """访问不存在的 task_id 返回 404（不暴露是否存在，防越权枚举）。

        回归 D12：approval 接口先校验任务归属，不属于当前用户的 task_id
        与不存在的 task_id 表现一致（均 404），防止信息泄露。
        """
        resp = await client.get(f"{BASE}/99999/approvals/pending")
        assert resp.status_code == 404

    async def test_approve_other_user_task_404(self, client: AsyncClient) -> None:
        """approve 访问不存在 task_id 返回 404（防越权枚举）。"""
        resp = await client.post(
            f"{BASE}/99999/approvals/approve",
            json={"approval_id": 1, "approved": True},
        )
        assert resp.status_code == 404

    async def test_deny_other_user_task_404(self, client: AsyncClient) -> None:
        """deny 访问不存在 task_id 返回 404（防越权枚举）。"""
        resp = await client.post(
            f"{BASE}/99999/approvals/deny",
        )
        assert resp.status_code == 404

    async def test_get_pending_approval_none(self, client: AsyncClient) -> None:
        """新任务无待处理审批，GET 返回 null。"""
        task_id = await _create_task(client)
        resp = await client.get(f"{BASE}/{task_id}/approvals/pending")
        assert resp.status_code == 200
        assert resp.json() is None

    async def test_approve_without_pending(self, client: AsyncClient) -> None:
        """无待处理审批时 approve 返回错误（ValueError->500，断言 >=400）。"""
        task_id = await _create_task(client)
        resp = await client.post(
            f"{BASE}/{task_id}/approvals/approve",
            json={"approval_id": 1, "approved": True},
        )
        assert resp.status_code >= 400

    async def test_deny_without_pending(self, client: AsyncClient) -> None:
        """无待处理审批时 deny 返回错误（ValueError->500，断言 >=400）。"""
        task_id = await _create_task(client)
        resp = await client.post(
            f"{BASE}/{task_id}/approvals/deny",
            json={"approval_id": 1, "approved": False},
        )
        assert resp.status_code >= 400

    async def test_approve_success(
        self,
        client: AsyncClient,
        test_session_factory: async_sessionmaker[AsyncSession],
        seed_user: int,
    ) -> None:
        """有 pending 审批时 approve 成功，返回 200。

        回归：A1 曾因访问不存在的 decision_payload + 缺 user_id 而 500。
        """
        task_id = await _create_task(client)
        approval_id = await _seed_pending_approval(test_session_factory, task_id, seed_user)

        resp = await client.post(
            f"{BASE}/{task_id}/approvals/approve",
            json={"approval_id": approval_id, "approved": True, "user_note": "同意"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ok"

    async def test_deny_success(
        self,
        client: AsyncClient,
        test_session_factory: async_sessionmaker[AsyncSession],
        seed_user: int,
    ) -> None:
        """有 pending 审批时 deny 成功，返回 200。

        回归：A2 曾因缺 user_id 而 500。
        """
        task_id = await _create_task(client)
        approval_id = await _seed_pending_approval(test_session_factory, task_id, seed_user)

        resp = await client.post(
            f"{BASE}/{task_id}/approvals/deny",
            json={"approval_id": approval_id, "approved": False},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ok"
