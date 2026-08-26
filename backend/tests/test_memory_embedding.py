"""记忆优雅降级 + 真实向量语义路径测试（接口报告 D03）。

覆盖两条路径：
- 降级路径（未配置向量模型）：精确内容去重 / 关键词检索 / 时间倒序上下文
- 配置路径（mock 真实 embedding API）：语义去重 / 语义检索 / 零向量占位行排除 /
  维度不符自动降级

策略实现见 service/memory.py（_generate_embedding 返回 None 即降级）与
repository/memory.py（semantic_search 排除占位零向量行）。
"""

from __future__ import annotations

import hashlib
import math
import random

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.active_config_registry import set_active_config
from app.repository.memory import ZERO_EMBEDDING, MemoryRepository
from app.service.setting import SettingsService

BASE = "/api/v1/memory"


@pytest.fixture(autouse=True)
def _clear_embedding_registry() -> None:
    """每用例清空 embedding 活动配置，避免跨用例串扰（注册表为模块级 dict）。"""
    set_active_config("embedding", {})
    yield
    set_active_config("embedding", {})


def _fake_vector(text: str) -> list[float]:
    """确定性伪向量：按文本 hash 生成 L2 归一化 512 维向量（单位范数，可算余弦）。

    同文本 → 同向量 → 余弦距离 0（相似度 1.0），供语义去重断言。
    """
    # 说明：测试确定性种子，非安全场景；S311/S324 在对应行单独豁免
    seed = int.from_bytes(hashlib.md5(text.encode()).digest()[:8], "big")  # noqa: S324
    rng = random.Random(seed)  # noqa: S311
    vec = [rng.random() for _ in range(512)]
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def _fake_embedding_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 service.memory.generate_embedding 换成确定性伪向量实现。"""

    async def fake_generate_embedding(
        *,
        api_key: str,  # noqa: ARG001 - 桩签名须与真函数一致，参数不参与逻辑
        base_url: str | None,  # noqa: ARG001
        model: str,  # noqa: ARG001
        text: str,
        timeout: float = 10.0,  # noqa: ARG001
    ) -> list[float]:
        return _fake_vector(text)

    monkeypatch.setattr("app.service.memory.generate_embedding", fake_generate_embedding)


def _mock_config_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 _generate_embedding 读到「已配置向量模型」。

    注册表为空 → 走 DB 回退分支 → 拦截 SettingsService.get_embedding_runtime_config
    直接返回配置 dict（避免真实 DB 读 + 明文 key 落库）。
    """

    async def fake_get_embedding_runtime_config(
        self: SettingsService,  # noqa: ARG001 - 桩返回固定配置，不读 self/db
        user_id: int,  # noqa: ARG001
    ) -> dict[str, object]:
        return {
            "provider": "openai",
            "base_url": None,
            "model": "text-embedding-3-small",
            "api_key": "sk-test-embedding",
        }

    monkeypatch.setattr(SettingsService, "get_embedding_runtime_config", fake_get_embedding_runtime_config)


class TestDegradedPath:
    """未配置向量模型 → 精确 / 关键词 / 时间倒序降级。"""

    async def test_add_exact_content_dedup(self, client: AsyncClient) -> None:
        """降级去重：同内容重复添加返回同一记忆（精确匹配替代语义去重）。"""
        r1 = await client.post(BASE, json={"type": "fact", "content": "用户期望薪资 25k-35k"})
        assert r1.status_code == 201
        r2 = await client.post(BASE, json={"type": "fact", "content": "用户期望薪资 25k-35k"})
        assert r2.status_code == 201
        assert r2.json()["id"] == r1.json()["id"]

    async def test_search_keyword_matches_content(self, client: AsyncClient) -> None:
        """降级检索：关键词命中内容返回结果。"""
        await client.post(BASE, json={"type": "preference", "content": "倾向远程工作"})
        resp = await client.post(f"{BASE}/search", json={"query": "远程", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "远程" in data[0]["content"]

    async def test_search_keyword_no_match_empty(self, client: AsyncClient) -> None:
        """降级检索：无关关键词返回空列表。"""
        await client.post(BASE, json={"type": "fact", "content": "期望薪资 30k"})
        resp = await client.post(f"{BASE}/search", json={"query": "完全不相关xyz", "top_k": 5})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_search_keyword_wildcard_escaped(self, client: AsyncClient) -> None:
        """降级检索：用户输入 % _ 转义为字面量，不当作通配符（零信任）。"""
        await client.post(BASE, json={"type": "fact", "content": "期望薪资 100%"})
        # 搜索 % 本身（被转义为字面 %），应命中
        resp = await client.post(f"{BASE}/search", json={"query": "100%", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    async def test_context_recent_fallback(self, client: AsyncClient) -> None:
        """降级上下文：任务无向量时按时间倒序返回最近记忆（标注 global）。"""
        await client.post(BASE, json={"type": "fact", "content": "用户偏好远程"})
        resp = await client.post(f"{BASE}/context/for-task/99999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["memories"][0]["content"] == "用户偏好远程"
        assert data["memories"][0]["source"] == "global"


class TestConfiguredPath:
    """已配置向量模型（mock API）→ 语义去重 / 语义检索 / 零占位行排除。"""

    async def test_configured_add_semantic_dedup(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """语义去重：同内容二次写入返回同一记忆（同向量相似度=1 ≥ 0.95）。"""
        _mock_config_configured(monkeypatch)
        _fake_embedding_api(monkeypatch)
        r1 = await client.post(BASE, json={"type": "fact", "content": "用户期望薪资 25k-35k"})
        assert r1.status_code == 201
        r2 = await client.post(BASE, json={"type": "fact", "content": "用户期望薪资 25k-35k"})
        assert r2.status_code == 201
        assert r2.json()["id"] == r1.json()["id"]

    async def test_configured_search_returns_similarity_score(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """语义检索：写入真向量后按相似度返回结果（合法 0~1 分数，不再 NaN）。"""
        _mock_config_configured(monkeypatch)
        _fake_embedding_api(monkeypatch)
        await client.post(BASE, json={"type": "preference", "content": "倾向远程工作"})
        resp = await client.post(f"{BASE}/search", json={"query": "远程", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert "similarity_score" in data[0]
        # 余弦相似度应为合法 0~1 数值（旧零向量占位路径为 NaN，恒被断言失败）
        assert 0.0 <= data[0]["similarity_score"] <= 1.0

    async def test_semantic_search_excludes_zero_placeholder(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        test_session_factory: async_sessionmaker[AsyncSession],
        seed_user: int,
    ) -> None:
        """零向量占位行不污染语义检索：直插占位 + 真向量，检索只回真向量行。

        回归 D03 根因：零向量余弦距离 NaN 会导致排序/去重全失效，故
        semantic_search 必须用 `!= ZERO_EMBEDDING` 排除历史占位行。
        """
        _mock_config_configured(monkeypatch)
        _fake_embedding_api(monkeypatch)

        # 走 API 写入一条真向量记忆
        created = await client.post(BASE, json={"type": "fact", "content": "真向量记忆"})
        assert created.status_code == 201
        real_id = created.json()["id"]

        # 直插一条零向量占位行（模拟未配置向量模型时期的存量数据）
        async with test_session_factory() as session:
            repo = MemoryRepository(session)
            placeholder = await repo.create(
                {
                    "user_id": seed_user,
                    "type": "fact",
                    "content": "占位零向量",
                    "embedding": ZERO_EMBEDDING,
                }
            )
            await session.commit()

        # 检索 → 只应命中真向量行（占位行被排除，避免 NaN 污染）
        resp = await client.post(f"{BASE}/search", json={"query": "真向量记忆", "top_k": 10})
        assert resp.status_code == 200
        data = resp.json()
        ids = {item["id"] for item in data}
        assert real_id in ids
        assert placeholder.id not in ids
        # 所有结果相似度均为合法数值（无 NaN 占位污染）
        for item in data:
            assert 0.0 <= item["similarity_score"] <= 1.0

    async def test_configured_dimension_mismatch_degrades(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """维度不符（mock API 返回 3 维）→ 视为未配置，自动走关键词降级。"""
        _mock_config_configured(monkeypatch)

        async def bad_dimension(
            *,
            api_key: str,  # noqa: ARG001 - 桩返回固定维度，忽略入参
            base_url: str | None,  # noqa: ARG001
            model: str,  # noqa: ARG001
            text: str,  # noqa: ARG001
            timeout: float = 10.0,  # noqa: ARG001
        ) -> list[float]:
            return [1.0, 0.0, 0.0]  # 3 维，与 Vector(512) 不符

        monkeypatch.setattr("app.service.memory.generate_embedding", bad_dimension)

        await client.post(BASE, json={"type": "fact", "content": "期望薪资 30k"})
        resp = await client.post(f"{BASE}/search", json={"query": "薪资", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        # 降级路径：关键词命中内容
        assert len(data) >= 1
        assert "薪资" in data[0]["content"]
