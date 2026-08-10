"""基础设施层。

职责：
- Redis 连接管理
- Redis Stream 优先级队列
- 分布式锁（待实现）
- Scheduler（待实现）
- MCP Client（待实现）

依赖方向：service -> infra -> redis/postgres，禁止反向。
"""

from .queue import QueueClient, QueueMessage, get_queue_client
from .redis import get_redis_client, get_redis_pool

__all__ = [
    "QueueClient",
    "QueueMessage",
    "get_queue_client",
    "get_redis_client",
    "get_redis_pool",
]
