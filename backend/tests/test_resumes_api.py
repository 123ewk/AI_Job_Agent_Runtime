"""简历域 API 集成测试。

覆盖 Resume CRUD + 设默认。字段契约与 Resume Model + DB 设计文档 02 对齐：
name（非 title）、status 默认 active、首个简历自动 is_default=True。
"""

from __future__ import annotations

from httpx import AsyncClient

BASE = "/api/v1/resumes"


def _resume_payload(name: str = "我的简历", **overrides: object) -> dict[str, object]:
    """构造合法的 ResumeCreate payload（V1 JSON 文本，非 multipart）。"""
    payload: dict[str, object] = {
        "name": name,
        "content": "姓名：张三\n技能：Python、FastAPI\n工作经验：3 年",
    }
    payload.update(overrides)
    return payload


class TestResumesAPI:
    """Resume CRUD 接口契约。"""

    async def test_create_first_resume(self, client: AsyncClient) -> None:
        """POST /resumes 创建简历：首个自动 is_default=True，status=active，version=1。"""
        resp = await client.post(BASE, json=_resume_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] > 0
        assert data["name"] == "我的简历"
        assert data["status"] == "active"
        assert data["version"] == 1
        assert data["is_default"] is True

    async def test_create_second_resume_not_default(self, client: AsyncClient) -> None:
        """第二个简历 is_default=False。"""
        await client.post(BASE, json=_resume_payload("第一份"))
        resp = await client.post(BASE, json=_resume_payload("第二份"))
        assert resp.status_code == 201
        assert resp.json()["is_default"] is False

    async def test_list_resumes_empty(self, client: AsyncClient) -> None:
        """GET /resumes 空列表返回分页结构。"""
        resp = await client.get(BASE)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_resumes_after_create(self, client: AsyncClient) -> None:
        """创建后列表含该简历。"""
        await client.post(BASE, json=_resume_payload("list-1"))
        resp = await client.get(BASE)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "list-1"

    async def test_get_resume_detail(self, client: AsyncClient) -> None:
        """GET /resumes/{id} 返回详情，含解析原文 content。"""
        create = await client.post(BASE, json=_resume_payload("detail-1"))
        resume_id = create.json()["id"]

        resp = await client.get(f"{BASE}/{resume_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == resume_id
        assert "Python" in data["content"]

    async def test_get_resume_not_found(self, client: AsyncClient) -> None:
        """不存在简历返回 >=400。"""
        resp = await client.get(f"{BASE}/99999")
        assert resp.status_code >= 400

    async def test_activate_sets_default(self, client: AsyncClient) -> None:
        """POST /resumes/{id}/activate：目标简历 is_default=True。"""
        first = (await client.post(BASE, json=_resume_payload("first"))).json()
        second = (await client.post(BASE, json=_resume_payload("second"))).json()
        assert first["is_default"] is True
        assert second["is_default"] is False

        resp = await client.post(f"{BASE}/{second['id']}/activate")
        assert resp.status_code == 200
        assert resp.json()["is_default"] is True

    async def test_activate_not_found(self, client: AsyncClient) -> None:
        """激活不存在的简历返回 >=400。"""
        resp = await client.post(f"{BASE}/99999/activate")
        assert resp.status_code >= 400

    async def test_delete_resume(self, client: AsyncClient) -> None:
        """DELETE /resumes/{id} 返回 StatusResponse，再查应错误。"""
        create = await client.post(BASE, json=_resume_payload("del-1"))
        resume_id = create.json()["id"]

        delete = await client.delete(f"{BASE}/{resume_id}")
        assert delete.status_code == 200
        assert delete.json()["status"] == "ok"

        after = await client.get(f"{BASE}/{resume_id}")
        assert after.status_code >= 400
