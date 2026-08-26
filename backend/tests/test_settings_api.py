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
from starlette.requests import Request

from app.api.v1.settings import push_active_config
from app.core.active_config_registry import get_active_config, set_active_config
from app.core.exceptions import BadRequestError
from app.schema.setting import ActiveConfigPush


class _StubLLMResponse:
    """探测响应桩。"""

    def __init__(self, status: int) -> None:
        self.status_code = status


class _StubLLMClient:
    """httpx.AsyncClient 探测桩：校验注入的认证头 + 探测 URL 协议，返回固定状态码。

    - header="Authorization" → 断言 Bearer <expected_secret>（OpenAI 兼容协议）
    - header="x-api-key"     → 断言 x-api-key <expected_secret>（anthropic 兼容协议）
    - url_suffix 断言探测路径确实按协议拼对（如 /models vs /v1/models）
    expected_secret 为 None 时跳过头校验（供失败场景用）。
    """

    def __init__(
        self,
        expected_secret: str | None,
        status: int,
        header: str,
        url_suffix: str,
    ) -> None:
        self._expected_secret = expected_secret
        self._status = status
        self._header = header
        self._url_suffix = url_suffix

    async def __aenter__(self) -> _StubLLMClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _StubLLMResponse:
        # 断言探测请求打对了协议端点（覆盖"用对了路径"）
        assert url.endswith(self._url_suffix), f"unexpected probe url: {url}"
        if self._expected_secret is not None:
            assert headers is not None
            if self._header == "x-api-key":
                assert headers.get("x-api-key") == self._expected_secret
            else:
                assert headers["Authorization"] == f"Bearer {self._expected_secret}"
        return _StubLLMResponse(self._status)


def _stub_httpx_connectivity(
    monkeypatch: pytest.MonkeyPatch,
    expected_auth: str | None,
    status: int,
    *,
    header: str = "Authorization",
    url_suffix: str = "/models",
) -> None:
    """把 settings 服务里的 httpx.AsyncClient 换成探测桩。"""

    def factory(*_args: object, **_kwargs: object) -> _StubLLMClient:
        return _StubLLMClient(expected_auth, status, header, url_suffix)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


class TestSettingsAPI:
    """Settings API 测试集。"""

    BASE_URL = "/api/v1/settings"

    async def test_get_all_settings(self, client: AsyncClient) -> None:
        """获取全量配置。

        期望：返回 5 个分类的列表，每项含 category + settings，
        缺失配置自动填充默认值。
        """
        resp = await client.get(self.BASE_URL)
        assert resp.status_code == 200
        data = resp.json()

        assert isinstance(data, list)
        assert len(data) == 5
        categories = {item["category"] for item in data}
        assert categories == {"llm", "agent", "job_rule", "reply_style", "embedding"}

        # llm 分类应含 provider 默认值
        llm_cat = next(item for item in data if item["category"] == "llm")
        llm_keys = {s["key"] for s in llm_cat["settings"]}
        assert "provider" in llm_keys

        # embedding 分类应含向量模型默认值（隐式 512 维，无 dimension 键）
        emb_cat = next(item for item in data if item["category"] == "embedding")
        emb_map = {s["key"]: s["value"] for s in emb_cat["settings"]}
        assert emb_map["provider"] == "openai"
        assert emb_map["model"] == "text-embedding-3-small"
        assert "api_key" in emb_map

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

    async def test_validate_llm_anthropic_v1(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """provider=anthropic 且 base 含 /v1 → 用 x-api-key 打 /v1/models（非 Bearer+/models）。"""
        _stub_httpx_connectivity(
            monkeypatch,
            "sk-anthropic",
            200,
            header="x-api-key",
            url_suffix="/v1/models",
        )
        resp = await client.post(
            f"{self.BASE_URL}/validate-llm",
            json={
                "provider": "anthropic",
                "base_url": "https://api.anthropic.com/v1",
                "model": "claude-3-sonnet",
                "api_key": "sk-anthropic",
                "temperature": 0.7,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_validate_llm_anthropic_compat_deepseek(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DeepSeek anthropic 兼容端点（base 含 /anthropic 标记）→ x-api-key + /anthropic/v1/models。

        回归修复：旧逻辑对 anthropic 端点硬拼 /models 得 404 误报「连接失败」。
        """
        _stub_httpx_connectivity(
            monkeypatch,
            "sk-deepseek-ac",
            200,
            header="x-api-key",
            url_suffix="/anthropic/v1/models",
        )
        resp = await client.post(
            f"{self.BASE_URL}/validate-llm",
            json={
                "provider": "deepseek",
                "base_url": "https://api.deepseek.com/anthropic",
                "model": "deepseek-chat",
                "api_key": "sk-deepseek-ac",
                "temperature": 0.7,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["detail"] is None

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

    async def test_get_embedding_config_defaults(self, client: AsyncClient) -> None:
        """GET /settings/embedding 未配置时返回默认向量模型。"""
        resp = await client.get(f"{self.BASE_URL}/embedding")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert data["model"] == "text-embedding-3-small"
        assert "api_key_masked" in data

    async def test_update_embedding_config(self, client: AsyncClient) -> None:
        """PUT /settings/embedding 保存向量模型配置，返回掩码 key。"""
        resp = await client.put(
            f"{self.BASE_URL}/embedding",
            json={
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "text-embedding-3-small",
                "api_key": "sk-emb-key-12345",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert data["model"] == "text-embedding-3-small"
        assert data["base_url"] == "https://api.openai.com/v1"
        assert data["api_key_masked"] is not None
        assert "sk-emb-key-12345" not in (data["api_key_masked"] or "")

    async def test_embedding_api_key_stored_encrypted(
        self,
        client: AsyncClient,
        test_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """embedding.api_key 落库为密文（与 llm.api_key 同规，泛化加密回归）。

        PUT 后直查 settings 表，断言 value 带 encrypted 标记且不含明文。
        """
        plain_key = "sk-emb-encrypt-987654321"
        put_resp = await client.put(
            f"{self.BASE_URL}/embedding",
            json={
                "provider": "openai",
                "base_url": None,
                "model": "text-embedding-3-small",
                "api_key": plain_key,
            },
        )
        assert put_resp.status_code == 200

        from sqlalchemy import select

        from app.models.setting import Setting

        async with test_session_factory() as session:
            result = await session.execute(
                select(Setting).where(Setting.category == "embedding", Setting.key == "api_key")
            )
            setting = result.scalar_one()
            stored = setting.value
            assert isinstance(stored, dict)
            assert stored.get("encrypted") is True
            assert plain_key not in str(stored["value"])

        # GET 应返回掩码（既非明文也非密文）
        get_resp = await client.get(f"{self.BASE_URL}/embedding")
        assert get_resp.status_code == 200
        masked = get_resp.json()["api_key_masked"]
        assert masked is not None
        assert plain_key not in masked

    async def test_get_all_masks_embedding_api_key(self, client: AsyncClient) -> None:
        """GET /settings 全量列表不得泄露 embedding.api_key 明文（泛化掩码回归）。"""
        plain_key = "sk-emb-leak-1234567890"
        await client.put(
            f"{self.BASE_URL}/embedding",
            json={
                "provider": "openai",
                "base_url": None,
                "model": "text-embedding-3-small",
                "api_key": plain_key,
            },
        )

        resp = await client.get(self.BASE_URL)
        assert resp.status_code == 200
        data = resp.json()

        emb_cat = next(item for item in data if item["category"] == "embedding")
        api_key_item = next(s for s in emb_cat["settings"] if s["key"] == "api_key")
        assert api_key_item["value"] != plain_key
        assert plain_key not in (api_key_item["value"] or "")


class TestActiveConfigPushAPI:
    """活动配置推送端点测试（方案 A /settings/active，本机限定）。"""

    BASE_URL = "/api/v1/settings"

    def _clear_registry(self) -> None:
        set_active_config("llm", {})
        set_active_config("job_rule", {})
        set_active_config("reply_style", {})
        set_active_config("embedding", {})

    async def test_push_active_writes_registry(self, client: AsyncClient) -> None:
        """本机推送 llm（含明文 api_key）→ 落注册表，响应不回吐 key。"""
        self._clear_registry()
        resp = await client.post(
            f"{self.BASE_URL}/active",
            json={
                "llm": {
                    "provider": "openai",
                    "base_url": None,
                    "model": "gpt-4o-mini",
                    "api_key": "sk-local-plaintext",
                    "temperature": 0.7,
                }
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        llm = get_active_config("llm")
        assert llm["api_key"] == "sk-local-plaintext"
        assert llm["model"] == "gpt-4o-mini"
        # 响应体绝不含明文 key
        assert "sk-local-plaintext" not in resp.text

    async def test_push_active_multiple_sections(self, client: AsyncClient) -> None:
        """一次推送 llm + job_rule 两段，两段都写入注册表。"""
        self._clear_registry()
        resp = await client.post(
            f"{self.BASE_URL}/active",
            json={
                "llm": {
                    "provider": "deepseek",
                    "base_url": None,
                    "model": "deepseek-chat",
                    "api_key": "sk-sections",
                    "temperature": 0.7,
                },
                "job_rule": {
                    "min_salary": 20,
                    "max_salary": 50,
                    "overtime_allowed": False,
                    "outsourcing_allowed": False,
                    "offsite_allowed": False,
                },
            },
        )
        assert resp.status_code == 200
        assert get_active_config("llm")["api_key"] == "sk-sections"
        job_rule = get_active_config("job_rule")
        assert job_rule["min_salary"] == 20
        assert job_rule["max_salary"] == 50

    async def test_push_active_embedding_section(self, client: AsyncClient) -> None:
        """推送 embedding 段（含明文 api_key）→ 落注册表，响应不回吐 key。"""
        self._clear_registry()
        resp = await client.post(
            f"{self.BASE_URL}/active",
            json={
                "embedding": {
                    "provider": "openai",
                    "base_url": None,
                    "model": "text-embedding-3-small",
                    "api_key": "sk-emb-local-plaintext",
                }
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        emb = get_active_config("embedding")
        assert emb["api_key"] == "sk-emb-local-plaintext"
        assert emb["model"] == "text-embedding-3-small"
        # 响应体绝不含明文 key
        assert "sk-emb-local-plaintext" not in resp.text

    async def test_push_non_local_rejected(self) -> None:
        """非本机来源直接拒绝（伪造 scope 直调路由函数断言抛 BadRequestError）。"""
        self._clear_registry()
        scope = {
            "type": "http",
            "method": "POST",
            "path": f"{self.BASE_URL}/active",
            "headers": [],
            "client": ("198.51.100.7", 55555),
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
            "root_path": "",
        }
        req = Request(scope)
        body = ActiveConfigPush(
            llm={
                "provider": "openai",
                "base_url": None,
                "model": "gpt-4o-mini",
                "api_key": "should-not-be-stored",
                "temperature": 0.7,
            }
        )
        with pytest.raises(BadRequestError):
            await push_active_config(req, body)
        # 拒绝后注册表应为空（llm 是本类的唯一预先填充段）
        assert get_active_config("llm") == {}
