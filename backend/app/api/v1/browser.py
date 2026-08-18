"""浏览器桥状态路由。

只读状态端点：enabled/running/extension_connected/token_configured/tools。
供前端（popup/sidepanel/控制台）展示浏览器能力可用性；不触发进程 spawn。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.infra.browser_mcp import get_browser_mcp
from app.service.browser_tools import TOOL_NAME_WHITELIST

router = APIRouter(prefix="/browser", tags=["browser"])


@router.get("/status")
async def get_browser_status() -> dict[str, object]:
    """浏览器桥状态（只读，不 spawn）。

    - enabled: BROWSER_MCP_ENABLED 是否开启
    - running: node server 子进程是否存活
    - extension_connected: Chrome 扩展是否已连上 /ws
    - token_configured: 令牌是否已配置（env 或 secrets 文件）
    - tools: 可用工具白名单
    """
    client = await get_browser_mcp()
    status = client.status()
    status["tools"] = sorted(TOOL_NAME_WHITELIST)
    return status


@router.get("/token")
async def get_browser_token() -> dict[str, str]:
    """返回浏览器桥令牌（供扩展 popup「一键获取」自动填入）。

    令牌来源与 mcp-server/token.js 同源：env 或 ~/.browser-mcp-secrets.json，
    因此扩展 popup 拿到的值就是 server /ws 校验的值。
    仅本机可访问：CORS 白名单 + 127.0.0.1 监听；token 是浏览器桥认证令牌，非后端账号凭据。
    """
    client = await get_browser_mcp()
    return {"token": client.token}
