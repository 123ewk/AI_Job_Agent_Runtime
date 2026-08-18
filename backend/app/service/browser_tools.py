"""浏览器工具适配器（Tool Adapter，doc 07 §6）。

职责：
- 把 Skill 目标翻译为 MCP Tool 调用（本轮为直接调用 chrome_* 工具）
- 安全校验：工具名白名单、URL 域名白名单（browser_mcp_url_whitelist）、
  高危工具标记（browser_mcp_risk_tools -> 需 Skill 级授权，直接拒绝返回）
- 浏览器锁（doc 04 runtime.locks.browser）：进程级 asyncio.Lock 串行化浏览器操作
- 超时/重启/重试：委托给 BrowserMcpClient.call
- observe 标准化：ToolResult{ok, data, error, screenshot?}
- 审计日志：append-only（execution_logs 契约：node="tool_executor"）。
  本轮 audit_sink 未接入时仅结构化日志；worker（doc 04）落地后接 execution_logs。

对齐红线：Skill 不写选择器；选择器由 Adapter/例程注册表持有。
交互写操作（发送/投递）属高危，需 doc 14 审批流 —— 本轮仅打标拒绝，审批后续迭代。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from structlog import get_logger

from app.core.config import Settings, get_settings
from app.infra.browser_mcp import BrowserMcpClient

logger = get_logger("service.browser_tools")

# doc 07 §5 的 18 个 MCP Tool（与 mcp-server/tools.js 注册名一致）
TOOL_NAME_WHITELIST: frozenset[str] = frozenset(
    {
        "get_windows_and_tabs",
        "chrome_switch_tab",
        "chrome_navigate",
        "chrome_close_tabs",
        "chrome_read_page",
        "chrome_get_web_content",
        "chrome_console",
        "chrome_click_element",
        "chrome_fill_or_select",
        "chrome_keyboard",
        "chrome_handle_dialog",
        "chrome_request_element_selection",
        "chrome_computer",
        "chrome_javascript",
        "chrome_screenshot",
        "chrome_network_capture",
        "chrome_network_request",
        "chrome_upload_file",
    }
)

# 携带 url 参数、需做域名白名单校验的工具
URL_PARAM_TOOLS: frozenset[str] = frozenset({"chrome_navigate", "chrome_network_request"})

# 进程级浏览器锁（所有 Adapter 实例共享，串行化浏览器操作）
_browser_lock = asyncio.Lock()

# 审计 task 引用集合：防止 asyncio.create_task 的 task 被 GC（与 approval.py 同款模式）
_audit_tasks: set[asyncio.Task[None]] = set()

# 审计 sink 签名：async (tool, args, result, error, latency_ms) -> None
AuditSink = Callable[..., Coroutine[Any, Any, None]]


@dataclass
class ToolResult:
    """标准化工具调用结果（供 ReAct observe / 前端消费）。"""

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    screenshot: str | None = None  # data URL（chrome_screenshot）
    raw: dict[str, Any] = field(default_factory=dict)


class BrowserToolAdapter:
    """浏览器工具适配器。"""

    def __init__(
        self,
        client: BrowserMcpClient | None = None,
        settings: Settings | None = None,
        *,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.audit_sink = audit_sink

    # ------------------------------------------------------------------
    # 安全校验
    # ------------------------------------------------------------------
    def _validate_name(self, name: str) -> str | None:
        if name not in TOOL_NAME_WHITELIST:
            return f"未知工具: {name}（白名单见 doc 07 §5）"
        return None

    def _validate_url(self, name: str, args: dict[str, Any]) -> str | None:
        if name not in URL_PARAM_TOOLS:
            return None
        url = (args or {}).get("url")
        if not url:
            return f"{name} 缺少 url 参数"
        try:
            hostname = urlparse(url).hostname or ""
        except ValueError:
            return f"url 非法: {url}"
        if not hostname:
            return f"url 缺少主机名: {url}"
        whitelist = self.settings.browser_mcp_url_whitelist_list
        if not whitelist:
            return f"{name} 目标域名 {hostname} 不在白名单（当前为空）"
        if not any(hostname == item or hostname.endswith("." + item) for item in whitelist):
            return f"{name} 目标域名 {hostname} 不在白名单: {','.join(whitelist)}"
        return None

    def _validate_risk(self, name: str) -> str | None:
        if name in self.settings.browser_mcp_risk_tools_list:
            return f"高危工具 {name} 需 Skill 级授权 + 审计（doc 07 §8），本轮未授权"
        return None

    # ------------------------------------------------------------------
    # 调用
    # ------------------------------------------------------------------
    async def call_tool(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> ToolResult:
        """调用浏览器工具（安全校验 -> 浏览器锁 -> MCP 调用 -> 标准化）。"""
        started = time.monotonic()
        args = args or {}
        error: str | None = None
        result: dict[str, Any] = {}
        try:
            if err := self._validate_name(name):
                error = err
                return ToolResult(ok=False, error=error)
            if err := self._validate_url(name, args):
                error = err
                return ToolResult(ok=False, error=error)
            if err := self._validate_risk(name):
                error = err
                return ToolResult(ok=False, error=error)
            if self.client is None:
                error = "浏览器客户端未注入（BROWSER_MCP_ENABLED=false）"
                return ToolResult(ok=False, error=error)

            timeout = timeout or self.settings.browser_mcp_timeout
            async with _browser_lock:
                result = await self.client.call(name, args, timeout=timeout)
            return self._normalize(result)
        except Exception as exc:
            error = str(exc)
            return ToolResult(ok=False, error=error)
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            self._audit(name, args, result, error, latency_ms)

    # ------------------------------------------------------------------
    # 标准化 / 审计
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(result: dict[str, Any]) -> ToolResult:
        content = result.get("content", [])
        texts = [c.get("text") for c in content if c.get("type") == "text" and c.get("text")]
        screenshot = next(
            (c.get("data") for c in content if c.get("type") == "image" and c.get("data")),
            None,
        )
        structured = result.get("structuredContent")
        if structured is not None:
            data = structured
        elif len(texts) == 1:
            raw = texts[0]
            try:
                data = json.loads(raw) if raw[:1] in ("{", "[") else {"text": raw}
            except json.JSONDecodeError:
                data = {"text": raw}
        else:
            data = {"text": "\n".join(texts)}
        return ToolResult(ok=True, data=data, screenshot=screenshot, raw=result)

    def _audit(
        self,
        name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        error: str | None,
        latency_ms: int,
    ) -> None:
        """审计：优先走注入的 sink（未来接 execution_logs），否则结构化日志。"""
        if self.audit_sink is not None:
            try:
                task: asyncio.Task[None] = asyncio.create_task(
                    self.audit_sink(name, args, result, error, latency_ms)
                )
                _audit_tasks.add(task)
                task.add_done_callback(_audit_tasks.discard)
            except Exception as exc:
                # 审计失败不阻塞调用，降级为结构化日志
                logger.warning("browser_audit_failed", error=str(exc))
            else:
                return
        logger.info(
            "browser_tool_called",
            tool=name,
            args=args,
            error=error,
            latency_ms=latency_ms,
            ok=error is None,
        )
