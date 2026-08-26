"""活动配置注册表核心单测（方案 A）。"""

from __future__ import annotations

import pytest

from app.core.active_config_registry import (
    ALLOWED_KINDS,
    get_active_config,
    set_active_config,
)


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """每用例前清空注册表（模块级 dict，防止用例间串扰）。"""
    yield
    set_active_config("llm", {})
    set_active_config("job_rule", {})
    set_active_config("reply_style", {})


class TestActiveConfigRegistry:
    def test_write_then_read_roundtrip(self) -> None:
        """写入 llm 后能读回（含 api_key 明文，供 Agent 运行时取用）。"""
        set_active_config("llm", {"api_key": "sk-plaintext", "model": "gpt-4o-mini"})
        got = get_active_config("llm")
        assert got["api_key"] == "sk-plaintext"
        assert got["model"] == "gpt-4o-mini"

    def test_unknown_kind_ignored(self) -> None:
        """非法 kind 写入被忽略，读回空。"""
        set_active_config("bogus", {"key": "value"})
        assert get_active_config("bogus") == {}

    def test_empty_when_unset(self) -> None:
        """未设置过的 kind 返回空 dict（而非 None）。"""
        assert get_active_config("llm") == {}

    def test_defensive_copy_on_read(self) -> None:
        """读回的是副本，篡改返回值不影响注册表内部态。"""
        set_active_config("llm", {"api_key": "sk-a"})
        got = get_active_config("llm")
        got["api_key"] = "sk-X"
        assert get_active_config("llm")["api_key"] == "sk-a"

    def test_defensive_copy_on_write(self) -> None:
        """写入的是副本（浅拷贝），调用方后续改 dict 不污染已存值。"""
        data = {"api_key": "sk-b"}
        set_active_config("llm", data)
        data["api_key"] = "sk-C"
        assert get_active_config("llm")["api_key"] == "sk-b"

    def test_allowed_kinds_whitelist(self) -> None:
        """白名单覆盖方案 A 三类配置。"""
        assert {"llm", "job_rule", "reply_style"} == ALLOWED_KINDS
