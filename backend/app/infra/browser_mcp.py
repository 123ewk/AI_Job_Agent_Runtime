"""浏览器桥 MCP 客户端（Chrome MCP Server 的 Python 侧）。

职责（对齐 doc 07 §4「MCP Client 管理 Server 子进程生命周期」）：
- 以子进程拉起 mcp-server/index.js（node），等待 /ping 就绪
- 30s 健康检查周期：ping 失败 -> 重启
- StreamableHTTP JSON-RPC：initialize(取 session id) -> notifications/initialized -> tools/call
- 单次调用超时 -> 重启 server -> 重试（attempts 上限 3）
- 令牌：settings.browser_mcp_token 优先，否则回退 ~/.browser-mcp-secrets.json
  （与 mcp-server/token.js 同源，与扩展 popup 粘贴的令牌天然一致）

生命周期：
- 由 app lifespan 在 BROWSER_MCP_ENABLED=true 时 start() / 关闭时 stop()
- 默认关闭：enabled=False 时本模块不 spawn 任何进程，不影响现有功能

依赖方向：service -> infra -> node 子进程（不反向）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from structlog import get_logger

from app.core.config import Settings, get_settings

logger = get_logger("infra.browser_mcp")

# 与 mcp-server/token.js 的 secrets 文件保持一致。
# 注意：路径在调用时求值（Path.home() 依赖 USERPROFILE，测试会替换该环境变量）。
SECRETS_FILE_NAME = ".browser-mcp-secrets.json"
INITIALIZE_PROTOCOL_VERSION = "2025-03-26"
WINDOWS_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_READY_TIMEOUT_S = 10.0
_PROC_STOP_GRACE_S = 3.0


class McpServerError(RuntimeError):
    """MCP 协议层错误（server 返回 isError / jsonrpc error）。"""


class McpServerNotRunningError(RuntimeError):
    """server 未启动（start 未调用或已崩溃且未恢复）。"""


class McpServerDisabledError(RuntimeError):
    """BROWSER_MCP_ENABLED=false，浏览器能力未启用。"""


def resolve_token(settings: Settings) -> str:
    """解析令牌：settings 显式配置优先，否则读 secrets 文件。

    扩展侧用户从 `node token.js --print` 复制的正是同一个值，
    因此三方（server / 扩展 / 后端）天然一致。
    """
    if settings.browser_mcp_token:
        return str(settings.browser_mcp_token)
    try:
        secrets_file = Path.home() / SECRETS_FILE_NAME
        secrets = json.loads(secrets_file.read_text("utf-8"))
        token = secrets.get("token") or ""
        if len(token) >= 32:
            return token
    except (OSError, ValueError, TypeError):
        pass
    return ""


class BrowserMcpClient:
    """Chrome MCP Server 的生命周期与 JSON-RPC 调用客户端。"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._token = resolve_token(self.settings)
        self._http_factory = http_client_factory  # 测试注入用
        self._http: httpx.AsyncClient | None = None
        self._proc: asyncio.subprocess.Process | None = None
        # 是否托管该 server：True = 自己 spawn 或接管复用（健康检查 + 崩溃重启）。
        # False = 从未启动。复用的外部 server 不设 _proc，stop 不杀它。
        self._managed = False
        self._session_id: str | None = None
        self._lock = asyncio.Lock()
        self._health_task: asyncio.Task[None] | None = None
        # 最近一次健康检查结果（status 端点消费）
        self._last_ping: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        # bool() 收敛：pydantic-settings 无类型 stub，字段可能被推断为 Any
        return bool(self.settings.browser_mcp_enabled)

    @property
    def running(self) -> bool:
        if self._proc is not None:
            return self._proc.returncode is None
        # 复用的外部 server（_proc 为空）视为运行中，由健康检查兜底验证
        return self._managed

    @property
    def token_configured(self) -> bool:
        return len(self._token) >= 32

    @property
    def token(self) -> str:
        """当前令牌（供 popup 一键获取 / 诊断）。

        注意：仅本机 localhost 可访问（CORS 白名单 + 127.0.0.1 监听），
        是浏览器桥的认证令牌，非后端账号凭据。
        """
        return self._token

    def status(self) -> dict[str, Any]:
        """只读状态（不 spawn，不阻塞）。"""
        return {
            "enabled": self.enabled,
            "running": self.running,
            "extension_connected": bool(self._last_ping and self._last_ping.get("extension")),
            "token_configured": self.token_configured,
            "last_ping": self._last_ping,
        }

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """确保浏览器桥可用（幂等）。

        策略（探测-复用-托管，保证手动 `npm start` 与后端托管互不冲突）：
        1. 若 12307 已有健康 server（无论谁启动的）→ 直接复用（不 spawn）。
        2. 否则自己 spawn 并接管。
        无论哪种方式都启动健康检查循环：外部 server 崩溃后由本客户端接管拉起。
        """
        if not self.enabled:
            logger.info("browser_mcp_disabled")
            return
        async with self._lock:
            if self.running:
                return
            if await self._probe():
                logger.info("browser_mcp_reusing_external_server", port=self.settings.browser_mcp_port)
                self._managed = True
            else:
                await self._spawn()
                self._managed = True
                await self._wait_ready()
            self._session_id = None
            self._health_task = asyncio.create_task(self._health_loop())
            logger.info("browser_mcp_started", port=self.settings.browser_mcp_port, managed=self._managed)

    async def stop(self) -> None:
        """优雅停止。

        只终止自己托管（spawn 或接管）的 server；外部手动启动的 server 不杀。
        """
        if self._health_task is not None:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
            self._health_task = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self._session_id = None
        if self._managed and self._proc is not None and self._proc.returncode is None:
            logger.info("browser_mcp_stopping")
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=_PROC_STOP_GRACE_S)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        self._proc = None
        self._managed = False
        self._last_ping = None

    async def restart(self) -> None:
        """崩溃恢复：若端口已被他人接管则复用，否则重新拉起。"""
        logger.warning("browser_mcp_restarting")
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=_PROC_STOP_GRACE_S)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        self._proc = None
        self._session_id = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        if self.enabled:
            if await self._probe():
                # 端口被外部进程接管（例如用户手动 npm start），复用之
                logger.info("browser_mcp_reusing_external_server", port=self.settings.browser_mcp_port)
            else:
                await self._spawn()
                await self._wait_ready()

    async def _probe(self) -> bool:
        """探测 12307 是否已有健康 server（一次性，不放宽超时）。"""
        try:
            await self.ping()
        except (httpx.HTTPError, OSError):
            return False
        else:
            return True

    # ------------------------------------------------------------------
    # 子进程
    # ------------------------------------------------------------------
    async def _spawn(self) -> None:
        server_path = self.settings.browser_mcp_server_path_resolved
        env = os.environ.copy()
        if self._token:
            env["BROWSER_MCP_TOKEN"] = self._token
        env["BROWSER_MCP_PORT"] = str(self.settings.browser_mcp_port)
        env["BROWSER_MCP_HOST"] = self.settings.browser_mcp_host

        log_file = Path(server_path).parent / "mcp-server.log"
        fh = log_file.open("a", encoding="utf-8")
        # 注意：Windows 下加 CREATE_NO_WINDOW，避免每次启动弹黑色控制台窗口
        self._proc = await asyncio.create_subprocess_exec(
            "node",
            str(server_path),
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            creationflags=WINDOWS_NO_WINDOW,
        )
        logger.info("browser_mcp_spawned", path=str(server_path), pid=self._proc.pid)

    async def _wait_ready(self) -> None:
        """等待 /ping 返回 200（最多 _READY_TIMEOUT_S）。"""
        async with asyncio.timeout(_READY_TIMEOUT_S):
            while True:
                try:
                    ping = await self.ping()
                except (httpx.HTTPError, OSError):
                    await asyncio.sleep(0.3)
                else:
                    self._last_ping = ping
                    return

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------
    async def _health_loop(self) -> None:
        interval = max(self.settings.browser_mcp_ping_interval, 5.0)
        while True:
            await asyncio.sleep(interval)
            if not self.enabled:
                break
            try:
                self._last_ping = await self.ping()
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("browser_mcp_health_failed", error=str(exc))
                # 自己 spawn 的子进程崩溃（returncode 非 None）或外部 server 消失：
                # 都重新拉起 / 探测接管。restart() 内部已有 _probe 复用逻辑。
                await self.restart()

    async def ping(self) -> dict[str, Any]:
        """GET /ping（无认证）。"""
        resp = await self._http_client().get("/ping", timeout=5.0)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        data["checked_at"] = datetime.now(UTC).isoformat()
        return data

    # ------------------------------------------------------------------
    # HTTP / MCP
    # ------------------------------------------------------------------
    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            if self._http_factory is not None:
                self._http = self._http_factory()
            else:
                base = f"http://{self.settings.browser_mcp_host}:{self.settings.browser_mcp_port}"
                headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
                self._http = httpx.AsyncClient(base_url=base, headers=headers)
        return self._http

    async def _post(
        self,
        payload: dict[str, Any],
        *,
        timeout: float,
        with_session: bool = False,
    ) -> dict[str, Any]:
        """发送 JSON-RPC 请求并解析响应（支持 SSE 与 JSON 两种返回格式）。"""
        return (await self._post_raw(payload, timeout=timeout, with_session=with_session))[0]

    async def _post_raw(
        self,
        payload: dict[str, Any],
        *,
        timeout: float,
        with_session: bool = False,
    ) -> tuple[dict[str, Any], httpx.Response]:
        """发送 JSON-RPC 请求，返回 (解析后的消息, 原始响应)。

        initialize 的 session id 位于 HTTP 响应头，需要原始响应才能拿到。
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if with_session and self._session_id:
            headers["mcp-session-id"] = self._session_id
        resp = await self._http_client().post("/mcp", json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return self._parse_response(resp, payload.get("id")), resp

    @staticmethod
    def _parse_response(resp: httpx.Response, req_id: object) -> dict[str, Any]:
        """从响应体解析 JSON-RPC 消息。

        server 用 StreamableHTTP transport：Accept 含 text/event-stream 时返回 SSE
        （每行 data: <json>）；也可能直接返回 JSON。两种都兼容。
        """
        text = resp.text
        if not text.strip():
            # notifications 类请求返回 202 + 空体（如 notifications/initialized）
            return {}
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            messages: list[dict[str, Any]] = []
            for raw_line in text.splitlines():
                stripped = raw_line.strip()
                if stripped.startswith("data:"):
                    payload = stripped[5:].strip()
                    if payload:
                        try:
                            messages.append(json.loads(payload))
                        except json.JSONDecodeError:
                            continue
            if not messages:
                empty_sse = "MCP server 返回了空的 SSE 流"
                raise McpServerError(empty_sse)
            # 优先取与请求 id 匹配的消息（流式可能有多条）
            for msg in messages:
                if msg.get("id") == req_id:
                    return msg
            return messages[-1]
        # 纯 JSON
        parsed: dict[str, Any] = json.loads(text)
        return parsed

    async def _ensure_session(self, timeout: float) -> None:
        """建立 MCP 会话（initialize -> notifications/initialized）。"""
        if self._session_id:
            return
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": INITIALIZE_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ai-job-agent-backend", "version": "1.0"},
            },
        }
        msg, resp = await self._post_raw(init_payload, timeout=timeout)
        if "error" in msg:
            raise McpServerError(str(msg["error"]))
        # session id 在 HTTP 响应头（initialize 的 onsessioninitialized 生成）
        self._session_id = resp.headers.get("mcp-session-id") or None
        # 通知初始化完成（无 id，返回 202）
        await self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=timeout,
            with_session=True,
        )

    # ------------------------------------------------------------------
    # 调用入口
    # ------------------------------------------------------------------
    async def call(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """调用 MCP 工具（超时 -> 重启 -> 重试，attempts 上限 3）。

        返回 server 的 tools/call result（含 content 列表）。
        """
        if not self.enabled:
            disabled_msg = "BROWSER_MCP_ENABLED=false，浏览器能力未启用"
            raise McpServerDisabledError(disabled_msg)
        if not self.running:
            not_running_msg = "Chrome MCP Server 未运行"
            raise McpServerNotRunningError(not_running_msg)
        timeout = timeout or self.settings.browser_mcp_timeout
        async with self._lock:
            attempts = 0
            while True:
                attempts += 1
                try:
                    await self._ensure_session(timeout)
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": args or {}},
                    }
                    msg = await self._post(payload, timeout=timeout, with_session=True)
                    if "error" in msg:
                        rpc_error = str(msg["error"])
                        raise McpServerError(rpc_error)
                    result = msg.get("result") or {}
                    if result.get("isError"):
                        text = self._first_text(result)
                        tool_failed = text or f"tool 执行失败: {name}"
                        raise McpServerError(tool_failed)
                except (httpx.HTTPError, OSError, TimeoutError) as exc:
                    logger.warning("browser_mcp_call_retry", tool=name, attempt=attempts, error=str(exc))
                    if attempts >= 3:
                        retry_exhausted = f"工具调用失败（已重试 {attempts - 1} 次）: {name}"
                        raise McpServerError(retry_exhausted) from exc
                    await self.restart()
                    if not self.running:
                        restart_failed = "Chrome MCP Server 重启失败"
                        raise McpServerNotRunningError(restart_failed) from exc
                else:
                    return result

    @staticmethod
    def _first_text(result: dict[str, Any]) -> str:
        for item in result.get("content", []):
            text = item.get("text")
            if isinstance(text, str) and text:
                return text
        return ""


# ---------------------------------------------------------------------------
# 模块级懒加载单例（与 db/base.py 的 _State 容器模式一致，避免 global 语句）
# ---------------------------------------------------------------------------
class _ClientState:
    """浏览器客户端单例状态容器。

    惰性创建：首次 get_browser_mcp() 才实例化（绑定当时传入的 settings）。
    测试可直接 new BrowserMcpClient(settings=...) 构造独立实例，不经此入口。
    """

    client: BrowserMcpClient | None = None

    def __init__(self) -> None:
        self.client = None


_browser_state = _ClientState()
_browser_mcp_lock = asyncio.Lock()


async def get_browser_mcp(settings: Settings | None = None) -> BrowserMcpClient:
    """返回进程级单例 BrowserMcpClient（double-checked locking）。"""
    if _browser_state.client is None:
        async with _browser_mcp_lock:
            if _browser_state.client is None:
                _browser_state.client = BrowserMcpClient(settings)
    return _browser_state.client
