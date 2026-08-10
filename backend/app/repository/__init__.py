"""数据访问层 Repository。

Service -> Repository -> DB 单向依赖。

所有 Repository 都通过 FastAPI Depends 注入，
生命周期与请求绑定（每个请求一个 AsyncSession）。

使用::

    from app.repository import UserRepository, JobRepository

    async def create_job(db: AsyncSession, data: JobCreate):
        repo = JobRepository(db)
        return await repo.create(data)
"""

from app.repository.approval import ApprovalRepository
from app.repository.base import BaseRepository
from app.repository.conversation import ConversationRepository
from app.repository.execution_log import ExecutionLogRepository
from app.repository.hr import HRRepository
from app.repository.job import JobRepository
from app.repository.memory import MemoryRepository
from app.repository.message import MessageRepository
from app.repository.resume import ResumeRepository
from app.repository.resume_summary import ResumeSummaryRepository
from app.repository.setting import SettingRepository
from app.repository.sync_record import SyncRecordRepository
from app.repository.task import TaskRepository
from app.repository.task_checkpoint_index import TaskCheckpointIndexRepository
from app.repository.user import UserRepository

__all__ = [
    "ApprovalRepository",
    "BaseRepository",
    "ConversationRepository",
    "ExecutionLogRepository",
    "HRRepository",
    "JobRepository",
    "MemoryRepository",
    "MessageRepository",
    "ResumeRepository",
    "ResumeSummaryRepository",
    "SettingRepository",
    "SyncRecordRepository",
    "TaskCheckpointIndexRepository",
    "TaskRepository",
    "UserRepository",
]
