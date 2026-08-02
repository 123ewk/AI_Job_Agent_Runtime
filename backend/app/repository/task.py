"""任务 Repository。"""

from __future__ import annotations

from sqlalchemy import select

from app.models.task import Task
from app.repository.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    """任务数据访问层。

    Task 是异步执行单元，状态机流转（doc 03）。
    与 Conversation/Job 可选绑定。
    """

    model = Task

    async def list_pending_or_running(self, limit: int = 100) -> list[Task]:
        """列出待执行/执行中任务（调度器拉取用）。"""
        result = await self.session.execute(
            select(Task)
            .where(Task.status.in_(("pending", "running")))
            .order_by(Task.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_thread_id(self, thread_id: str, limit: int = 20) -> list[Task]:
        """按 Thread ID 列出关联任务（断点续跑 / 日志追溯用）。"""
        result = await self.session.execute(
            select(Task)
            .where(Task.thread_id == thread_id)
            .order_by(Task.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def cancel_by_id(self, task_id: int) -> bool:
        """取消任务（更新状态为 canceled）。"""
        await self.session.execute(
            select(Task).where(Task.id == task_id).with_for_update()
        )
        task = await self.get(task_id)
        if task is None or task.status in ("succeeded", "failed", "canceled"):
            return False
        task.status = "canceled"  # type: ignore[attr-defined]
        return True
