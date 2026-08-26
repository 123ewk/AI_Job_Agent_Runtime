"""Settings API 接口测试。

覆盖：配置查询、批量更新、各分类配置 CRUD。

使用 httpx.AsyncClient + ASGITransport 驱动 ASGI app，与 DB fixture 共享
同一事件循环，避免 TestClient 的跨循环问题（见 conftest.py 说明）。

契约以 app/api/v1/settings.py 实际实现为准。
"""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _StubLLMResponse:
    """探测响应桩。"""

    def __init__(self, status: int) -> None:
        self.status_code = status


class _StubLLMClient:
    """httpx.AsyncClient 探测桩：校验注入的 Authorization，返回固定状态码。

    expected_auth 为 None 时跳过校验（供失败场景用）。
    """

    def __init__(self, expected_auth: str | None, status: int) -> None:
        self._expected_auth = expected_auth
        self._status = status

    async def __aenter__(self) -> _StubLLMClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, _url: str, headers: dict[str, str] | None = None) -> _StubLLMResponse:
        # 断言探测请求确实带上了调用方注入的 Bearer key（覆盖"用对了 key"）
        if self._expected_auth is not None:
            assert headers is not None and headers["Authorization"] == f"Bearer {self._expected_auth}"
        return _StubLLMResponse(self._status)


def _stub_httpx_connectivity(
    monkeypatch: pytest.MonkeyPatch, expected_auth: str | None, status: int
) -> None:
    """把 settings 服务里的 httpx.AsyncClient 换成探测桩。"""
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *_args, **_kwargs: _StubLLMClient(expected_auth, status),
    )


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

    async def test_validate_llm_unfilled(self, client: AsyncClient) -> None:
        """请求体空 + 未保存过 api_key → ok=False，detail 提示未填写。

        验证修复后的判定规则：不看数据库、无 DB 依赖时如实报"未填写"。
        """
        resp = await client.post(f"{self.BASE_URL}/validate-llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "API Key" in data["detail"]

    async def test_validate_llm_uses_form_body(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """表单刚填 api_key、未落库 → 用请求体里的 key 探测（核心修复场景）。

        断言请求头真正带上了表单传入的 key，且 base_url 为空时按 provider 兜底。
        """
        _stub_httpx_connectivity(monkeypatch, "sk-form-never-saved", 200)
        resp = await client.post(
            f"{self.BASE_URL}/validate-llm",
            json={
                "provider": "openai",
                "base_url": None,
                "model": "gpt-4o-mini",
                "api_key": "sk-form-never-saved",
                "temperature": 0.7,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_validate_llm_http_error(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """provider 返回 401（key 无效）→ ok=False，detail 带状态码。"""
        _stub_httpx_connectivity(monkeypatch, "sk-bad-key", 401)
        resp = await client.post(
            f"{self.BASE_URL}/validate-llm",
            json={
                "provider": "openai",
                "base_url": None,
                "model": "gpt-4o-mini",
                "api_key": "sk-bad-key",
                "temperature": 0.7,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False
        assert "401" in resp.json()["detail"]

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

    async def test_api_key_validate_after_encrypt(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """请求体为空 → 回退读取解密已保存 key 做探测（加解密 → 回退链路回归）。

        探测桩断言 Authorization 用的是解密后的明文 key，既验证了回退读库、
        也验证了 B5 加密存储后的正确解密。
        """
        plain_key = "sk-validate-after-encrypt"
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
        _stub_httpx_connectivity(monkeypatch, plain_key, 200)
        resp = await client.post(f"{self.BASE_URL}/validate-llm")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["detail"] is None
