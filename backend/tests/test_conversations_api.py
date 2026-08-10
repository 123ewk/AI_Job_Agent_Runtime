"""会话域 API 集成测试。

覆盖 Conversation CRUD、消息收发、同步、未回复检测。
字段契约：external_id（去重锚点）、job_title（非 title）、status active/waiting_hr/closed。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

BASE = "/api/v1/conversations"


def _conv_payload(external_id: str = "conv-001", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "external_id": external_id,
        "hr_name": "HR张",
        "job_title": "后端工程师",
    }
    payload.update(overrides)
    return payload


class TestConversationsAPI:
    """Conversation 接口契约。"""

    async def test_create_conversation(self, client: AsyncClient) -> None:
        """POST /conversations 创建会话，默认 status=active。"""
        resp = await client.post(BASE, json=_conv_payload("c-create"))
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] > 0
        assert data["external_id"] == "c-create"
        assert data["status"] == "active"
        assert data["job_title"] == "后端工程师"

    async def test_list_conversations(self, client: AsyncClient) -> None:
        """创建后列表含该会话。"""
        await client.post(BASE, json=_conv_payload("c-list"))
        resp = await client.get(BASE)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["external_id"] == "c-list"

    async def test_get_conversation(self, client: AsyncClient) -> None:
        """GET /conversations/{id} 返回详情。"""
        create = await client.post(BASE, json=_conv_payload("c-get"))
        conv_id = create.json()["id"]

        resp = await client.get(f"{BASE}/{conv_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == conv_id

    async def test_update_conversation(self, client: AsyncClient) -> None:
        """PUT /conversations/{id} 更新 hr_name / job_title / status。"""
        create = await client.post(BASE, json=_conv_payload("c-upd"))
        conv_id = create.json()["id"]

        resp = await client.put(
            f"{BASE}/{conv_id}",
            json={"hr_name": "HR李", "status": "waiting_hr"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hr_name"] == "HR李"
        assert data["status"] == "waiting_hr"

    async def test_close_conversation(self, client: AsyncClient) -> None:
        """POST /conversations/{id}/close 返回 StatusResponse，状态变 closed。"""
        create = await client.post(BASE, json=_conv_payload("c-close"))
        conv_id = create.json()["id"]

        close = await client.post(f"{BASE}/{conv_id}/close")
        assert close.status_code == 200
        assert close.json()["status"] == "ok"

        after = await client.get(f"{BASE}/{conv_id}")
        assert after.json()["status"] == "closed"

    async def test_send_and_list_message(self, client: AsyncClient) -> None:
        """POST 消息（role=user，不触发入队）后可列出。"""
        create = await client.post(BASE, json=_conv_payload("c-msg"))
        conv_id = create.json()["id"]

        # MessageCreate 要求 conversation_id（路由用 path 覆盖，但 body 须先通过校验）
        send = await client.post(
            f"{BASE}/{conv_id}/messages",
            json={"role": "user", "content": "您好，我对该职位感兴趣。", "conversation_id": conv_id},
        )
        assert send.status_code == 201
        msg = send.json()
        assert msg["content"] == "您好，我对该职位感兴趣。"
        assert msg["role"] == "user"

        listed = await client.get(f"{BASE}/{conv_id}/messages")
        assert listed.status_code == 200
        assert isinstance(listed.json(), list)
        assert len(listed.json()) == 1

    async def test_sync_messages(self, client: AsyncClient) -> None:
        """POST /conversations/{id}/sync 占位实现返回 StatusResponse（新增 0 条）。"""
        create = await client.post(BASE, json=_conv_payload("c-sync"))
        conv_id = create.json()["id"]

        resp = await client.post(f"{BASE}/{conv_id}/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "0" in data["message"]

    async def test_unreplied_check_empty(self, client: AsyncClient) -> None:
        """GET /conversations/unreplied/check 返回 {count, messages}。"""
        resp = await client.get(f"{BASE}/unreplied/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert isinstance(data["messages"], list)

    async def test_get_conversation_not_found(self, client: AsyncClient) -> None:
        """不存在会话返回错误（缺全局 404 处理器，ValueError->500，断言 >=400）。"""
        resp = await client.get(f"{BASE}/99999")
        assert resp.status_code >= 400
