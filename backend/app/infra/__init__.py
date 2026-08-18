"""基础设施层。

职责：
- Redis 连接管理
- Redis Stream 优先级队列
- 分布式锁（待实现）
- Scheduler（待实现）
- MCP Client（已实现：Chrome MCP Server 生命周期 + StreamableHTTP JSON-RPC）

依赖方向：service -> infra -> redis/postgres/node 子进程，禁止反向。
"""

from .browser_mcp import (
    BrowserMcpClient,
    McpServerDisabledError,
    McpServerError,
    McpServerNotRunningError,
    get_browser_mcp,
    resolve_token,
)
from .queue import QueueClient, QueueMessage, get_queue_client
from .redis import get_redis_client, get_redis_pool

__all__ = [
    "BrowserMcpClient",
    "McpServerDisabledError",
    "McpServerError",
    "McpServerNotRunningError",
    "QueueClient",
    "QueueMessage",
    "get_browser_mcp",
    "get_queue_client",
    "get_redis_client",
    "get_redis_pool",
    "resolve_token",
]
