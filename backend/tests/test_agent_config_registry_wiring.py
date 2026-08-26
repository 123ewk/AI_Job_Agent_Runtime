"""Agent 装配工厂改道注册表（方案 A）回归测试。

覆盖两处读配置改道：
- create_planner_from_settings（workflow_engine.py）
- create_fallback_llm_from_settings（fallback.py）

行为契约（方案 A）：
- 注册表已填充 → 用注册表的明文 api_key / model（不触 DB，session_factory 不被调）
- 注册表空 → 回退已存 DB 配置（过渡期/进程重启后未重推时不回归）
- 两者皆空 → planner 抛 PlannerConfigError / fallback 返回 None
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.agent.runtime.workflow_engine import (
    PlannerConfigError,
    create_planner_from_settings,
)
from app.agent.tools.fallback import create_fallback_llm_from_settings
from app.core.active_config_registry import set_active_config


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _db_hitting_session_factory() -> Callable[[], _FakeSession]:
    """DB 回退用 session_factory：返回一个可 async with 的假会话。

    真实 async_sessionmaker() 是同步调用后直接返回 AsyncSession（非协程），
    故这里 factory 必须是同步函数，仅在其后再 async with 进入上下文。
    """

    def factory() -> _FakeSession:
        return _FakeSession()

    return factory


def _no_db_session_factory() -> Callable[[], _FakeSession]:
    """探测用 session_factory：一旦被调即报错，证明注册表路径未触 DB。"""

    def factory() -> _FakeSession:
        msg = "注册表已填充时不应访问 DB（session_factory 被意外调用）"
        raise AssertionError(msg)

    return factory


_LUM_CONF = {
    "provider": "openai",
    "base_url": None,
    "model": "gpt-4o-mini",
    "api_key": "db-fallback-key",
    "temperature": 0.7,
}


class _StubSettingsService:
    """伪装 SettingsService：get_llm_runtime_config 回 DB 假配置。"""

    def __init__(self, _db: object) -> None:
        pass

    async def get_llm_runtime_config(self, _user_id: int) -> dict[str, object]:
        return dict(_LUM_CONF)


class _EmptySettingsService:
    """伪装 SettingsService：回空配置（DB 里也没配）。"""

    def __init__(self, _db: object) -> None:
        pass

    async def get_llm_runtime_config(self, _user_id: int) -> dict[str, object]:
        return {}


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    """每用例结束清空注册表，防串扰。"""
    yield
    set_active_config("llm", {})
    set_active_config("job_rule", {})
    set_active_config("reply_style", {})


class TestCreatePlannerRegisterWiring:
    async def test_registry_populated_wins_over_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """注册表已填明文 api_key → planner 用之，不触 DB。"""
        monkeypatch.setattr("app.service.setting.SettingsService", _StubSettingsService)
        set_active_config("llm", {"api_key": "registry-key", "model": "gpt-reg"})
        planner = await create_planner_from_settings(_no_db_session_factory(), 1)
        assert planner._config.api_key == "registry-key"
        assert planner._config.model == "gpt-reg"

    async def test_registry_empty_falls_back_to_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """注册表空 → 回退 DB 已存配置。"""
        monkeypatch.setattr("app.service.setting.SettingsService", _StubSettingsService)
        set_active_config("llm", {})
        planner = await create_planner_from_settings(_db_hitting_session_factory(), 1)
        assert planner._config.api_key == "db-fallback-key"

    async def test_empty_everywhere_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """注册表空 + DB 空 → 抛 PlannerConfigError 引导用户配置。"""
        monkeypatch.setattr("app.service.setting.SettingsService", _EmptySettingsService)
        set_active_config("llm", {})
        with pytest.raises(PlannerConfigError):
            await create_planner_from_settings(_db_hitting_session_factory(), 1)


class TestCreateFallbackLLMWiring:
    async def test_registry_populated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.service.setting.SettingsService", _StubSettingsService)
        set_active_config("llm", {"api_key": "registry-key", "model": "gpt-reg"})
        llm = await create_fallback_llm_from_settings(_no_db_session_factory(), 1)
        assert llm is not None
        assert llm._config.api_key == "registry-key"

    async def test_registry_empty_falls_back_to_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.service.setting.SettingsService", _StubSettingsService)
        set_active_config("llm", {})
        llm = await create_fallback_llm_from_settings(_db_hitting_session_factory(), 1)
        assert llm is not None
        assert llm._config.api_key == "db-fallback-key"

    async def test_empty_everywhere_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.service.setting.SettingsService", _EmptySettingsService)
        set_active_config("llm", {})
        llm = await create_fallback_llm_from_settings(_db_hitting_session_factory(), 1)
        assert llm is None
