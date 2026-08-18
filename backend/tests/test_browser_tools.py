"""BrowserToolAdapter 单测（mock client，不连真实 server）。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.service.browser_tools import BrowserToolAdapter, ToolResult


# ---------------------------------------------------------------------------
# 测试用 Settings 替身
# ---------------------------------------------------------------------------
class FakeSettings:
    browser_mcp_url_whitelist = "zhipin.com"
    browser_mcp_risk_tools = "chrome_javascript,chrome_network_request"
    browser_mcp_timeout = 30.0

    @property
    def browser_mcp_url_whitelist_list(self) -> list[str]:
        return [i.strip() for i in self.browser_mcp_url_whitelist.split(",") if i.strip()]

    @property
    def browser_mcp_risk_tools_list(self) -> list[str]:
        return [i.strip() for i in self.browser_mcp_risk_tools.split(",") if i.strip()]


def make_adapter(mock_client: AsyncMock | None = None) -> BrowserToolAdapter:
    client = mock_client or AsyncMock()
    return BrowserToolAdapter(client=client, settings=FakeSettings())


def _ok_call(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------------------
# 工具名白名单
# ---------------------------------------------------------------------------
async def test_unknown_tool_rejected() -> None:
    adapter = make_adapter()
    result = await adapter.call_tool("evil_tool", {})
    assert isinstance(result, ToolResult)
    assert result.ok is False
    assert "未知工具" in (result.error or "")
    adapter.client.call.assert_not_awaited()


# ---------------------------------------------------------------------------
# URL 域名白名单
# ---------------------------------------------------------------------------
async def test_navigate_whitelisted_url_ok() -> None:
    adapter = make_adapter()
    adapter.client.call = AsyncMock(return_value=_ok_call('{"ok": true}'))
    result = await adapter.call_tool("chrome_navigate", {"url": "https://www.zhipin.com/web/geek/jobs"})
    assert result.ok is True
    adapter.client.call.assert_awaited_once()


async def test_navigate_blocked_domain() -> None:
    adapter = make_adapter()
    result = await adapter.call_tool("chrome_navigate", {"url": "https://evil.com/steal"})
    assert result.ok is False
    assert "不在白名单" in (result.error or "")


async def test_navigate_missing_url() -> None:
    adapter = make_adapter()
    result = await adapter.call_tool("chrome_navigate", {})
    assert result.ok is False
    assert "url" in (result.error or "")


async def test_read_page_not_url_checked() -> None:
    """非 URL 工具不做域名校验（不误伤 chrome_read_page）。"""
    adapter = make_adapter()
    adapter.client.call = AsyncMock(return_value=_ok_call('{"page": "x"}'))
    result = await adapter.call_tool("chrome_read_page", {"tabId": 1})
    assert result.ok is True


# ---------------------------------------------------------------------------
# 高危工具
# ---------------------------------------------------------------------------
async def test_risk_tool_rejected_without_approval() -> None:
    adapter = make_adapter()
    result = await adapter.call_tool("chrome_javascript", {"code": "1"})
    assert result.ok is False
    assert "高危工具" in (result.error or "")
    adapter.client.call.assert_not_awaited()


# ---------------------------------------------------------------------------
# 无 client（disabled）
# ---------------------------------------------------------------------------
async def test_no_client_rejected() -> None:
    adapter = BrowserToolAdapter(client=None, settings=FakeSettings())
    result = await adapter.call_tool("chrome_read_page", {})
    assert result.ok is False
    assert "BROWSER_MCP_ENABLED" in (result.error or "")


# ---------------------------------------------------------------------------
# 标准化 / 异常
# ---------------------------------------------------------------------------
async def test_normalize_json_text() -> None:
    adapter = make_adapter()
    adapter.client.call = AsyncMock(return_value=_ok_call('{"title": "岗位", "salary": "20k"}'))
    result = await adapter.call_tool("chrome_get_web_content", {})
    assert result.ok is True
    assert result.data == {"title": "岗位", "salary": "20k"}


async def test_normalize_screenshot() -> None:
    adapter = make_adapter()
    adapter.client.call = AsyncMock(
        return_value={"content": [{"type": "image", "data": "BASE64PNG", "mimeType": "image/png"}]}
    )
    result = await adapter.call_tool("chrome_screenshot", {})
    assert result.ok is True
    assert result.screenshot == "BASE64PNG"


async def test_exception_mapped_to_error() -> None:
    adapter = make_adapter()
    adapter.client.call = AsyncMock(side_effect=RuntimeError("server crashed"))
    result = await adapter.call_tool("chrome_read_page", {})
    assert result.ok is False
    assert "server crashed" in (result.error or "")


async def test_browser_lock_serializes() -> None:
    """并发调用串行化（进程级浏览器锁）。"""
    adapter = make_adapter()
    order: list[str] = []

    async def slow_call(name: str, _args: dict, timeout: float | None = None) -> dict:  # noqa: ARG001 - AsyncMock 按关键字传参，参数名必须匹配
        order.append(f"start:{name}")
        await asyncio.sleep(0.02)
        order.append(f"end:{name}")
        return _ok_call("ok")

    adapter.client.call = AsyncMock(side_effect=slow_call)

    await asyncio.gather(
        adapter.call_tool("chrome_read_page", {}),
        adapter.call_tool("chrome_get_web_content", {}),
    )
    # 锁保证同一时刻只有一个调用进入执行段
    assert order[0] == "start:chrome_read_page"
    assert order[-1] == "end:chrome_get_web_content"
    assert "end:chrome_read_page" in order
