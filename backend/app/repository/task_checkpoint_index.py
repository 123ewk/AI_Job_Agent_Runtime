"""Task-Checkpoint 索引 Repository。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select

from app.models.task_checkpoint_index import TaskCheckpointIndex
from app.repository.base import BaseRepository


class TaskCheckpointIndexRepository(BaseRepository[TaskCheckpointIndex]):
    """Task 与 LangGraph Checkpoint 映射索引数据访问层。

    状态：active（任务进行中）/ terminal（任务终态）。
    """

    model = TaskCheckpointIndex

    async def get_by_task(self, task_id: int) -> TaskCheckpointIndex | None:
        """获取任务对应的 Checkpoint 索引。"""
        return await self.get_by_unique(task_id=task_id)

    async def get_by_thread_id(self, thread_id: UUID) -> TaskCheckpointIndex | None:
        """按 LangGraph thread_id 查找索引。"""
        return await self.get_by_unique(thread_id=thread_id)

    async def get_latest_by_task(self, task_id: int) -> TaskCheckpointIndex | None:
        """获取任务最新的 Checkpoint 索引。"""
        result = await self.session.execute(
            select(TaskCheckpointIndex)
            .where(TaskCheckpointIndex.task_id == task_id)
            .order_by(desc(TaskCheckpointIndex.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_terminal(self, index_id: int) -> TaskCheckpointIndex | None:
        """标记为终态（任务完成/失败/取消时调用）。"""
        return await self.update(index_id, {"status": "terminal"})
