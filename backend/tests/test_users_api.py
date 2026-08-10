"""用户域 API 集成测试。

覆盖 GET /users/me、/users/me/tasks、/users/me/stats。
全部走 httpx.AsyncClient + ASGITransport（同事件循环），与 conftest 的 client fixture 配合。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

BASE = "/api/v1/users"


class TestUsersAPI:
    """用户接口契约。"""

    async def test_get_current_user(self, client: AsyncClient, seed_user: int) -> None:
        """GET /me 返回当前用户基本信息（V1 单用户模式）。"""
        resp = await client.get(f"{BASE}/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == seed_user
        assert data["is_active"] is True
        assert "email" in data

    async def test_get_my_tasks_empty(self, client: AsyncClient) -> None:
        """GET /me/tasks 空列表返回标准分页结构。"""
        resp = await client.get(f"{BASE}/me/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 20

    async def test_get_my_tasks_with_status_filter(self, client: AsyncClient) -> None:
        """按状态过滤任务列表（合法 status 值不报错）。"""
        resp = await client.get(f"{BASE}/me/tasks", params={"status": "running"})
        assert resp.status_code == 200
        assert isinstance(resp.json()["items"], list)

    async def test_get_my_stats(self, client: AsyncClient) -> None:
        """GET /me/stats 返回任务/会话/职位计数。"""
        resp = await client.get(f"{BASE}/me/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_tasks"] == 0
        assert data["active_conversations"] == 0
        assert data["total_jobs"] == 0

    @pytest.mark.skip(reason="多用户模式 V2+ 才有，V1 单用户无注册/登录接口")
    async def test_user_auth_not_implemented(self, client: AsyncClient) -> None:
        """占位：JWT 登录/注册在 V2+ 实现。"""
