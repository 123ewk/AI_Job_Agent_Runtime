"""BrowserMcpClient 单测（mock httpx，不连真实 server / 不 spawn 子进程）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.infra.browser_mcp import (
    BrowserMcpClient,
    McpServerDisabledError,
    McpServerError,
    McpServerNotRunningError,
    resolve_token,
)


# ---------------------------------------------------------------------------
# 测试用 Settings 替身（仅暴露本模块消费的字段）
# ---------------------------------------------------------------------------
class FakeSettings:
    browser_mcp_enabled = True
    browser_mcp_host = "127.0.0.1"
    browser_mcp_port = 12307
    browser_mcp_token = "a" * 32
    browser_mcp_timeout = 30.0
    browser_mcp_ping_interval = 30.0

    @property
    def browser_mcp_server_path_resolved(self) -> str:
        return "C:/fake/mcp-server/index.js"


class FakeSettingsDisabled:
    browser_mcp_enabled = False
    browser_mcp_host = "127.0.0.1"
    browser_mcp_port = 12307
    browser_mcp_token = ""
    browser_mcp_timeout = 30.0
    browser_mcp_ping_interval = 30.0

    @property
    def browser_mcp_server_path_resolved(self) -> str:
        return ""


# ---------------------------------------------------------------------------
# resolve_token
# ---------------------------------------------------------------------------
def test_resolve_token_settings_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """settings 显式 token 优先于 secrets 文件。"""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    settings = SimpleNamespace(browser_mcp_token="b" * 40)
    assert resolve_token(settings) == "b" * 40


def test_resolve_token_falls_back_to_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """settings 为空时回退 secrets 文件（browser-mcp-lite 兼容格式）。"""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    secrets = tmp_path / ".browser-mcp-secrets.json"
    secrets.write_text(json.dumps({"token": "c" * 40}), encoding="utf-8")
    settings = SimpleNamespace(browser_mcp_token="")
    assert resolve_token(settings) == "c" * 40


def test_resolve_token_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """文件缺失且 settings 为空 -> 返回空串。"""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    settings = SimpleNamespace(browser_mcp_token="")
    assert resolve_token(settings) == ""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _resp(content: str = "", headers: dict[str, str] | None = None) -> httpx.Response:
    """构造可 raise_for_status 的响应（httpx 要求 request 已挂载）。"""
    return httpx.Response(
        200,
        headers=headers or {},
        content=content,
        request=httpx.Request("POST", "http://127.0.0.1:12307/mcp"),
    )


def _fake_proc() -> SimpleNamespace:
    """伪造子进程句柄：带 terminate/kill/wait 供 restart 调用。"""
    return SimpleNamespace(
        returncode=None,
        pid=9999,
        terminate=lambda: None,
        kill=lambda: None,
        wait=AsyncMock(return_value=0),
    )


def _fake_http(post: Callable[..., Awaitable[httpx.Response]]) -> SimpleNamespace:
    """伪造 httpx client：post 协程 + aclose（restart 会调用）。"""
    return SimpleNamespace(post=post, aclose=AsyncMock())


# ---------------------------------------------------------------------------
# call 的异常语义
# ---------------------------------------------------------------------------
def test_call_disabled() -> None:
    """enabled=False 时 call 抛 McpServerDisabledError。"""
    client = BrowserMcpClient(FakeSettingsDisabled())
    with pytest.raises(McpServerDisabledError):
        asyncio.run(client.call("chrome_read_page", {}))


@pytest.mark.asyncio
async def test_call_not_running() -> None:
    """server 未启动时 call 抛 McpServerNotRunningError。"""
    client = BrowserMcpClient(FakeSettings())
    with pytest.raises(McpServerNotRunningError):
        await client.call("chrome_read_page", {})


@pytest.mark.asyncio
async def test_call_success_and_parse() -> None:
    """调用成功：initialize + initialized + tools/call，SSE 响应解析正确。"""
    client = BrowserMcpClient(FakeSettings())
    # 伪造 running（跳过真实 spawn）
    client._proc = _fake_proc()
    messages: list[dict[str, Any]] = [
        {
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": True}},
            },
            "jsonrpc": "2.0",
            "id": 1,
        },
        {"result": {"content": [{"type": "text", "text": json.dumps({"title": "t"})}]}, "jsonrpc": "2.0", "id": 2},
    ]
    sse_headers = {"mcp-session-id": "sess-abc", "content-type": "text/event-stream"}

    def sse_for(msg: dict[str, Any]) -> str:
        return f"event: message\ndata: {json.dumps(msg)}\n"

    async def fake_post(_url: str, **kwargs: object) -> httpx.Response:
        body = kwargs.get("json") or {}
        if body.get("method") == "tools/call":
            return _resp(sse_for(messages[1]), sse_headers)
        if body.get("method") == "initialize":
            return _resp(sse_for(messages[0]), sse_headers)
        return _resp("")

    client._http_factory = lambda: _fake_http(fake_post)
    with patch.object(client, "_spawn"), patch.object(client, "_wait_ready"):
        result = await client.call("chrome_read_page", {"tabId": 1})
    assert result["content"][0]["text"] == json.dumps({"title": "t"})
    assert client._session_id == "sess-abc"


@pytest.mark.asyncio
async def test_call_timeout_triggers_restart() -> None:
    """tools/call 超时 -> restart -> 重试 -> 成功。"""
    client = BrowserMcpClient(FakeSettings())
    client._proc = _fake_proc()
    attempts: dict[str, int] = {"n": 0}

    async def fake_post(_url: str, **kwargs: object) -> httpx.Response:
        body = kwargs.get("json") or {}
        if body.get("method") == "tools/call":
            attempts["n"] += 1
            if attempts["n"] == 1:
                timeout_msg = "timeout"
                raise httpx.ReadTimeout(timeout_msg, request=httpx.Request("POST", "http://x/mcp"))
            msg = {"result": {"content": [{"type": "text", "text": "ok"}]}, "jsonrpc": "2.0", "id": 2}
            sse_headers = {"mcp-session-id": "sess-x", "content-type": "text/event-stream"}
            return _resp(f"event: message\ndata: {json.dumps(msg)}\n", sse_headers)
        if body.get("method") == "initialize":
            msg = {"result": {}, "jsonrpc": "2.0", "id": 1}
            sse_headers = {"mcp-session-id": "sess-x", "content-type": "text/event-stream"}
            return _resp(f"event: message\ndata: {json.dumps(msg)}\n", sse_headers)
        return _resp("")

    client._http_factory = lambda: _fake_http(fake_post)
    restarted: dict[str, int] = {"n": 0}

    async def fake_restart() -> None:
        restarted["n"] += 1

    with (
        patch.object(client, "_spawn"),
        patch.object(client, "_wait_ready"),
        patch.object(client, "restart", fake_restart),
    ):
        result = await client.call("chrome_read_page", {})
    assert restarted["n"] == 1
    assert attempts["n"] == 2
    assert client._first_text(result) == "ok"


@pytest.mark.asyncio
async def test_call_error_after_retries() -> None:
    """持续超时 -> 3 次尝试后抛 McpServerError。

    restart 在真实环境会重建 _proc；测试中 patch 为 no-op，仅验证重试次数与异常语义。
    """
    client = BrowserMcpClient(FakeSettings())
    client._proc = _fake_proc()

    async def fake_post(_url: str, **_kwargs: object) -> httpx.Response:
        timeout_msg = "timeout"
        raise httpx.ReadTimeout(timeout_msg, request=httpx.Request("POST", "http://x/mcp"))

    client._http_factory = lambda: _fake_http(fake_post)
    with (
        patch.object(client, "_spawn"),
        patch.object(client, "_wait_ready"),
        patch.object(client, "restart"),
        pytest.raises(McpServerError, match="已重试"),
    ):
        await client.call("chrome_read_page", {})


@pytest.mark.asyncio
async def test_ping_returns_extension_state() -> None:
    """ping 解析 /ping 响应并带 checked_at。"""
    client = BrowserMcpClient(FakeSettings())

    async def fake_get(_url: str, timeout: float | None = None) -> httpx.Response:  # noqa: ARG001 - 关键字参数名必须匹配调用方
        return _resp(json.dumps({"status": "ok", "extension": True}), {"content-type": "application/json"})

    client._http_factory = lambda: SimpleNamespace(get=fake_get)
    ping = await client.ping()
    assert ping["status"] == "ok"
    assert ping["extension"] is True
    assert "checked_at" in ping


# ---------------------------------------------------------------------------
# 生命周期（禁用态 start/stop 幂等，不 spawn）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_disabled_noop() -> None:
    """enabled=False 时 start 不 spawn、不健康循环。"""
    client = BrowserMcpClient(FakeSettingsDisabled())
    await client.start()
    assert client._proc is None
    assert client._managed is False
    await client.stop()


@pytest.mark.asyncio
async def test_start_reuses_external_server() -> None:
    """端口已有健康 server -> 复用（不 spawn），并进入托管（崩溃后接管拉起）。"""
    client = BrowserMcpClient(FakeSettings())

    async def fake_probe() -> bool:
        return True

    with patch.object(client, "_probe", fake_probe), patch.object(client, "_spawn") as spawn_mock:
        await client.start()
    assert client._managed is True
    assert client._proc is None  # 未自己 spawn
    spawn_mock.assert_not_awaited()
    await client.stop()


@pytest.mark.asyncio
async def test_start_spawns_when_absent() -> None:
    """端口无 server -> 自己 spawn 并接管。"""
    client = BrowserMcpClient(FakeSettings())

    async def fake_probe() -> bool:
        return False

    with (
        patch.object(client, "_probe", fake_probe),
        patch.object(client, "_spawn"),
        patch.object(client, "_wait_ready"),
    ):
        await client.start()
    assert client._managed is True
    await client.stop()


@pytest.mark.asyncio
async def test_stop_does_not_kill_external_server() -> None:
    """复用外部 server 时 stop 不杀它（无 _proc 句柄）。"""
    client = BrowserMcpClient(FakeSettings())
    client._managed = True  # 模拟 adopt 外部 server
    client._proc = None
    await client.stop()
    # 无异常即通过；外部进程不受影响
    assert client._managed is False

