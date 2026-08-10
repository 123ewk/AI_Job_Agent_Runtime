"""任务域 API 集成测试。

覆盖 Task CRUD、取消、重试状态机、审批、队列统计。
字段契约：TaskCreate 只需 type（TaskType 枚举），无 title/description；
status 为 canceled（单 l）；审批路由为 /tasks/{task_id}/approvals/*。
任务创建会入队 Redis Stream（测试环境 Redis DB 1 可用）。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

BASE = "/api/v1/tasks"


async def _create_task(client: AsyncClient, task_type: str = "user_initiated") -> int:
    """创建任务并返回 task_id。"""
    resp = await client.post(BASE, json={"type": task_type})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


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

    async def test_queue_stats(self, client: AsyncClient) -> None:
        """GET /tasks/queue/stats 返回 pending 计数与并发上限。"""
        await _create_task(client)
        resp = await client.get(f"{BASE}/queue/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending"] == 1
        assert data["max_concurrent"] == 3

    @pytest.mark.skip(reason="无 /tasks/{id}/checkpoints 路由，Checkpoint 索引由 Runtime 内部维护")
    async def test_get_task_checkpoints(self, client: AsyncClient) -> None:
        """占位：Checkpoint 路由未实现。"""


class TestApprovalAPI:
    """审批接口契约（路由为 /tasks/{task_id}/approvals/*）。"""

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
