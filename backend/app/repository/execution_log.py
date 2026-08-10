"""执行日志 Repository。"""

from __future__ import annotations

from sqlalchemy import and_, desc, select

from app.models.execution_log import ExecutionLog
from app.repository.base import BaseRepository


class ExecutionLogRepository(BaseRepository[ExecutionLog]):
    """执行日志数据访问层（append-only）。

    注意：日志只追加，不更新、不删除。
    """

    model = ExecutionLog

    async def list_by_task(
        self,
        task_id: int,
        limit: int | None = 100,
        offset: int | None = None,
    ) -> list[ExecutionLog]:
        """按任务列出执行日志（倒序）。"""
        stmt = (
            select(ExecutionLog)
            .where(ExecutionLog.task_id == task_id)
            .order_by(desc(ExecutionLog.created_at))
        )
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_trace_id(self, trace_id: str) -> list[ExecutionLog]:
        """按全链路 Trace ID 列出日志。"""
        return await self.list_by_filter({"trace_id": trace_id}, order_by="created_at")

    async def list_by_node(
        self,
        task_id: int,
        node: str,
        limit: int | None = None,
    ) -> list[ExecutionLog]:
        """按任务 + LangGraph 节点列出日志。"""
        return await self.list_by_filter(
            {"task_id": task_id, "node": node},
            order_by="created_at",
            limit=limit,
        )

    async def list_error_logs(
        self,
        task_id: int,
        limit: int | None = None,
    ) -> list[ExecutionLog]:
        """列出任务的错误日志（error 字段非空）。"""
        result = await self.session.execute(
            select(ExecutionLog)
            .where(
                and_(
                    ExecutionLog.task_id == task_id,
                    ExecutionLog.error.is_not(None),
                )
            )
            .order_by(desc(ExecutionLog.created_at))
            .limit(limit or 50)
        )
        return list(result.scalars().all())

    async def count_by_task(self, task_id: int) -> int:
        """统计任务日志条数。"""
        result = await self.session.execute(
            select(ExecutionLog.id).where(ExecutionLog.task_id == task_id)
        )
        return len(result.scalars().all())

    async def get_avg_latency_by_node(
        self,
        task_id: int,
        node: str,
    ) -> float | None:
        """统计某节点的平均执行耗时（性能分析用）。"""
        result = await self.session.execute(
            select(ExecutionLog.latency_ms).where(
                and_(
                    ExecutionLog.task_id == task_id,
                    ExecutionLog.node == node,
                    ExecutionLog.latency_ms.is_not(None),
                )
            )
        )
        latencies = [x for x in result.scalars().all() if x is not None]
        if not latencies:
            return None
        return sum(latencies) / len(latencies)
