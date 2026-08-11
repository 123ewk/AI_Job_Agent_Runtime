"""Settings API 接口测试。

覆盖：配置查询、批量更新、各分类配置 CRUD。

使用 httpx.AsyncClient + ASGITransport 驱动 ASGI app，与 DB fixture 共享
同一事件循环，避免 TestClient 的跨循环问题（见 conftest.py 说明）。

契约以 app/api/v1/settings.py 实际实现为准。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TestSettingsAPI:
    """Settings API 测试集。"""

    BASE_URL = "/api/v1/settings"

    async def test_get_all_settings(self, client: AsyncClient) -> None:
        """获取全量配置。

        期望：返回 4 个分类的列表，每项含 category + settings，
        缺失配置自动填充默认值。
        """
        resp = await client.get(self.BASE_URL)
        assert resp.status_code == 200
        data = resp.json()

        assert isinstance(data, list)
        assert len(data) == 4
        categories = {item["category"] for item in data}
        assert categories == {"llm", "agent", "job_rule", "reply_style"}

        # llm 分类应含 provider 默认值
        llm_cat = next(item for item in data if item["category"] == "llm")
        llm_keys = {s["key"] for s in llm_cat["settings"]}
        assert "provider" in llm_keys

    async def test_get_llm_config(self, client: AsyncClient) -> None:
        """获取 LLM 分类配置。"""
        resp = await client.get(f"{self.BASE_URL}/llm")
        assert resp.status_code == 200
        data = resp.json()

        assert "provider" in data
        assert "model" in data
        assert "temperature" in data
        # api_key 仅返回掩码字段，不返回明文
        assert "api_key_masked" in data

    async def test_get_agent_config(self, client: AsyncClient) -> None:
        """获取 Agent 策略配置。"""
        resp = await client.get(f"{self.BASE_URL}/agent")
        assert resp.status_code == 200
        data = resp.json()

        assert "concurrency_limit" in data
        assert "auto_reply_enabled" in data
        assert "auto_approval_threshold" in data
        assert "approval_timeout_seconds" in data
        assert "max_retries" in data

    async def test_get_job_rule_config(self, client: AsyncClient) -> None:
        """获取投递规则配置。"""
        resp = await client.get(f"{self.BASE_URL}/job-rule")
        assert resp.status_code == 200
        data = resp.json()

        assert "min_salary" in data
        assert "max_salary" in data
        assert "overtime_allowed" in data

    async def test_get_reply_style_config(self, client: AsyncClient) -> None:
        """获取回复风格配置。"""
        resp = await client.get(f"{self.BASE_URL}/reply-style")
        assert resp.status_code == 200
        data = resp.json()

        assert "tone" in data
        assert "formality" in data

    async def test_batch_update_settings(self, client: AsyncClient) -> None:
        """批量更新配置（单分类多键）。

        期望：事务原子性，返回 updated 计数，更新后查询生效。
        """
        payload = {
            "category": "llm",
            "updates": [
                {"key": "provider", "value": "openai"},
                {"key": "model", "value": "gpt-4o-mini"},
            ],
        }
        resp = await client.put(f"{self.BASE_URL}/batch", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "ok"
        assert data["updated"] == 2

        # 验证更新生效
        resp_llm = await client.get(f"{self.BASE_URL}/llm")
        assert resp_llm.json()["provider"] == "openai"
        assert resp_llm.json()["model"] == "gpt-4o-mini"

    async def test_update_single_category(self, client: AsyncClient) -> None:
        """更新单个分类配置（PUT /llm，需含必填 api_key）。"""
        payload = {
            "provider": "anthropic",
            "base_url": None,
            "model": "claude-3-sonnet",
            "api_key": "sk-test-key-12345",
            "temperature": 0.7,
        }
        resp = await client.put(f"{self.BASE_URL}/llm", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["provider"] == "anthropic"
        assert data["model"] == "claude-3-sonnet"
        assert data["temperature"] == 0.7
        # api_key 应回收为掩码
        assert data["api_key_masked"] is not None

    async def test_get_all_masks_api_key(self, client: AsyncClient) -> None:
        """GET /settings 全量列表不得泄露 api_key 明文（A3 回归）。"""
        plain_key = "sk-leak-check-1234567890"
        await client.put(
            f"{self.BASE_URL}/llm",
            json={
                "provider": "openai",
                "base_url": None,
                "model": "gpt-4o-mini",
                "api_key": plain_key,
                "temperature": 0.7,
            },
        )

        resp = await client.get(self.BASE_URL)
        assert resp.status_code == 200
        data = resp.json()

        llm_cat = next(item for item in data if item["category"] == "llm")
        api_key_item = next(s for s in llm_cat["settings"] if s["key"] == "api_key")
        # 掩码后不应包含明文子串
        assert api_key_item["value"] != plain_key
        assert plain_key not in (api_key_item["value"] or "")

    @pytest.mark.skip(reason="listening HTTP 路由尚未实现（Service 方法存在，待路由接线 + 存储键补全）")
    async def test_get_listening_state(self, client: AsyncClient) -> None:
        """获取监听状态。"""
        resp = await client.get(f"{self.BASE_URL}/listening")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert isinstance(data["enabled"], bool)

    @pytest.mark.skip(reason="listening HTTP 路由尚未实现（Service 方法存在，待路由接线 + 存储键补全）")
    async def test_update_listening_state(self, client: AsyncClient) -> None:
        """更新监听状态。"""
        payload = {"enabled": True}
        resp = await client.put(f"{self.BASE_URL}/listening", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True

    async def test_validate_llm_settings(self, client: AsyncClient) -> None:
        """LLM 配置连通性校验（占位实现，未配置 api_key 时返回 ok=False）。"""
        resp = await client.post(f"{self.BASE_URL}/validate-llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert "detail" in data

    async def test_api_key_stored_encrypted(
        self,
        client: AsyncClient,
        test_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """api_key 落库为密文（B5 回归）。

        PUT 后直查 settings 表，断言 value 带 encrypted 标记且不含明文；
        GET /settings/llm 返回掩码而非密文或明文。
        """
        plain_key = "sk-encrypt-check-987654321"
        put_resp = await client.put(
            f"{self.BASE_URL}/llm",
            json={
                "provider": "openai",
                "base_url": None,
                "model": "gpt-4o-mini",
                "api_key": plain_key,
                "temperature": 0.7,
            },
        )
        assert put_resp.status_code == 200

        # 直查 DB：api_key 行应为密文
        from sqlalchemy import select

        from app.models.setting import Setting

        async with test_session_factory() as session:
            result = await session.execute(
                select(Setting).where(Setting.category == "llm", Setting.key == "api_key")
            )
            setting = result.scalar_one()
            stored = setting.value
            assert isinstance(stored, dict)
            assert stored.get("encrypted") is True
            assert plain_key not in str(stored["value"])

        # GET 应返回掩码（既非明文也非密文）
        get_resp = await client.get(f"{self.BASE_URL}/llm")
        assert get_resp.status_code == 200
        masked = get_resp.json()["api_key_masked"]
        assert masked is not None
        assert plain_key not in masked

    async def test_api_key_validate_after_encrypt(self, client: AsyncClient) -> None:
        """加密后 validate 能识别已配置 api_key（解密存在性检查正常）。"""
        await client.put(
            f"{self.BASE_URL}/llm",
            json={
                "provider": "openai",
                "base_url": None,
                "model": "gpt-4o-mini",
                "api_key": "sk-validate-after-encrypt",
                "temperature": 0.7,
            },
        )
        resp = await client.post(f"{self.BASE_URL}/validate-llm")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True  # 已配置 → 占位实现返回 True
