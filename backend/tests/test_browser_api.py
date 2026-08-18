"""/api/v1/browser/status 端点测试。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_browser_status_default(client: AsyncClient) -> None:
    """默认（BROWSER_MCP_ENABLED=false）返回 disabled 状态且列出工具白名单。

    token_configured 依赖本机 ~/.browser-mcp-secrets.json 是否存在，不做硬断言。
    """
    resp = await client.get("/api/v1/browser/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["running"] is False
    assert isinstance(body["token_configured"], bool)
    # 18 个 doc 07 工具白名单
    assert "chrome_read_page" in body["tools"]
    assert "chrome_click_element" in body["tools"]
    assert len(body["tools"]) >= 18


@pytest.mark.asyncio
async def test_browser_token_endpoint(client: AsyncClient) -> None:
    """GET /api/v1/browser/token 返回令牌（同源 secrets 文件，供 popup 一键获取）。

    注意：本机若存在 ~/.browser-mcp-secrets.json，返回的是该文件 token。
    """
    resp = await client.get("/api/v1/browser/token")
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert isinstance(body["token"], str)
    assert len(body["token"]) >= 32 or body["token"] == ""
