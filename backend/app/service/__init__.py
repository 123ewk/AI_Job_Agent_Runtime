"""业务逻辑层 Service。

API -> Service -> Repository 单向依赖。Service 不直接写 SQL，不依赖 HTTP。
Service 负责：
- 业务编排与校验
- 事务边界控制
- 跨 Repository 协调
- 事件发布（WS、Queue）

使用::

    from app.service import SettingsService, TaskService

    async def update_settings(db: AsyncSession, user_id: int, data: ...):
        service = SettingsService(db)
        return await service.update(user_id, data)
"""

from app.service.approval import ApprovalService
from app.service.conversation import ConversationService
from app.service.job import JobService
from app.service.memory import MemoryService
from app.service.resume import ResumeService
from app.service.setting import SettingsService
from app.service.task import TaskService

__all__ = [
    "ApprovalService",
    "ConversationService",
    "JobService",
    "MemoryService",
    "ResumeService",
    "SettingsService",
    "TaskService",
]
