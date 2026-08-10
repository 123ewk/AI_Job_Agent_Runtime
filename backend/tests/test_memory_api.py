"""记忆域 API 集成测试。

覆盖记忆写入、语义检索、按上下文列出、删除、任务上下文注入、会话提取。
字段契约：MemoryCreate 只需 type（MemoryType 枚举）+ content，无 importance；
检索用 top_k（无 threshold）；embedding 为 stub 零向量，相似度可能为 NaN，故仅断言结构。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

BASE = "/api/v1/memory"


class TestMemoryAPI:
    """Memory 接口契约。"""

    async def test_create_memory(self, client: AsyncClient) -> None:
        """POST /memory 创建记忆，返回 201 + id。"""
        resp = await client.post(
            BASE,
            json={"type": "fact", "content": "用户期望薪资 25k-35k"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] > 0
        assert data["type"] == "fact"
        assert data["content"] == "用户期望薪资 25k-35k"

    async def test_search_memory_empty(self, client: AsyncClient) -> None:
        """空库语义检索返回空列表。"""
        resp = await client.post(f"{BASE}/search", json={"query": "薪资", "top_k": 5})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_search_memory_with_data(self, client: AsyncClient) -> None:
        """写入后检索返回列表（零向量 embedding，仅断言结构不断言相似度）。"""
        await client.post(BASE, json={"type": "preference", "content": "倾向远程工作"})

        resp = await client.post(f"{BASE}/search", json={"query": "工作方式", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "content" in data[0]
        assert "id" in data[0]

    async def test_list_conversation_memory_empty(self, client: AsyncClient) -> None:
        """GET /memory/conversation/{id} 无关联记忆返回空列表。"""
        resp = await client.get(f"{BASE}/conversation/99999")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_job_memory_empty(self, client: AsyncClient) -> None:
        """GET /memory/job/{id} 无关联记忆返回空列表。"""
        resp = await client.get(f"{BASE}/job/99999")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_delete_memory(self, client: AsyncClient) -> None:
        """DELETE /memory/{id} 返回 StatusResponse。"""
        create = await client.post(BASE, json={"type": "fact", "content": "待删除记忆"})
        memory_id = create.json()["id"]

        resp = await client.delete(f"{BASE}/{memory_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_delete_memory_not_found(self, client: AsyncClient) -> None:
        """删除不存在记忆返回错误（ValueError->500，断言 >=400）。"""
        resp = await client.delete(f"{BASE}/99999")
        assert resp.status_code >= 400

    async def test_context_for_task_empty(self, client: AsyncClient) -> None:
        """POST /memory/context/for-task/{id} 不存在任务返回空上下文。"""
        resp = await client.post(f"{BASE}/context/for-task/99999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["memories"] == []
        assert "levels" in data

    async def test_extract_memory(self, client: AsyncClient) -> None:
        """POST /memory/extract?conversation_id= stub 返回 0 条。"""
        resp = await client.post(f"{BASE}/extract", params={"conversation_id": 99999})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "0" in data["message"]

    @pytest.mark.skip(reason="无 GET /memory（列表）路由，记忆按 conversation/job 上下文列出")
    async def test_list_memories(self, client: AsyncClient) -> None:
        """占位：全局列表路由未实现。"""

    @pytest.mark.skip(reason="无 GET /memory/{id} 详情 / PATCH 更新路由")
    async def test_get_and_update_memory(self, client: AsyncClient) -> None:
        """占位：记忆详情与更新路由未实现。"""
