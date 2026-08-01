"""ORM 模型集合（14 表，doc 09 目标态）。

导入所有模型以便 Base.metadata 收集全部表定义，
供 Alembic autogenerate 与迁移使用。新增表时在此注册。
"""

from __future__ import annotations

from app.db.base import Base
from app.models.approval import Approval
from app.models.conversation import Conversation
from app.models.execution_log import ExecutionLog
from app.models.hr import HR
from app.models.job import Job
from app.models.memory import Memory
from app.models.message import Message
from app.models.resume import Resume
from app.models.resume_summary import ResumeSummary
from app.models.setting import Setting
from app.models.sync_record import SyncRecord
from app.models.task import Task
from app.models.task_checkpoint_index import TaskCheckpointIndex
from app.models.user import User

__all__ = [
    "HR",
    "Approval",
    "Base",
    "Conversation",
    "ExecutionLog",
    "Job",
    "Memory",
    "Message",
    "Resume",
    "ResumeSummary",
    "Setting",
    "SyncRecord",
    "Task",
    "TaskCheckpointIndex",
    "User",
]
