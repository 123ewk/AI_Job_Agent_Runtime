"""长期记忆 Repository。"""

from __future__ import annotations

from sqlalchemy import and_, or_, select

from app.models.memory import Memory
from app.repository.base import BaseRepository


class MemoryRepository(BaseRepository[Memory]):
    """长期记忆数据访问层。

    支持按类型、关联会话/岗位过滤，以及向量语义检索。
    """

    model = Memory

    async def list_by_user(
        self,
        user_id: int,
        memory_type: str | None = None,
        limit: int | None = None,
    ) -> list[Memory]:
        """按用户列出记忆，可选按类型过滤。"""
        filters = {"user_id": user_id}
        if memory_type is not None:
            filters["type"] = memory_type
        return await self.list_by_filter(filters, limit=limit)

    async def list_by_conversation(self, conversation_id: int, limit: int = 50) -> list[Memory]:
        """按会话关联列出记忆。"""
        return await self.list_by_filter({"conversation_id": conversation_id}, limit=limit)

    async def list_by_job(self, job_id: int, limit: int = 50) -> list[Memory]:
        """按岗位关联列出记忆。"""
        return await self.list_by_filter({"job_id": job_id}, limit=limit)

    async def semantic_search(  # noqa: PLR0917
        self,
        user_id: int,
        query_vector: list[float],
        limit: int = 10,
        conversation_id: int | None = None,
        job_id: int | None = None,
        memory_type: str | None = None,
    ) -> list[tuple[Memory, float]]:
        """长期记忆语义检索（Top-K 注入 Planner）。

        可按会话/岗位/类型进一步过滤，缩小检索范围。
        """
        clauses = [Memory.user_id == user_id]
        if conversation_id is not None:
            clauses.append(Memory.conversation_id == conversation_id)
        if job_id is not None:
            clauses.append(Memory.job_id == job_id)
        if memory_type is not None:
            clauses.append(Memory.type == memory_type)

        result = await self.session.execute(
            select(
                Memory,
                Memory.embedding.cosine_distance(query_vector).label("distance"),
            )
            .where(and_(*clauses))
            .order_by("distance")
            .limit(limit)
        )
        return [(row.Memory, row.distance) for row in result.all()]

    async def semantic_search_cross_context(
        self,
        user_id: int,
        query_vector: list[float],
        conversation_id: int | None = None,
        job_id: int | None = None,
        limit: int = 10,
    ) -> list[tuple[Memory, float]]:
        """跨上下文语义检索（优先返回当前会话/岗位相关记忆，其次全局）。

        排序逻辑：匹配 conversation_id/job_id 的优先，然后按相似度。
        """
        clauses = [Memory.user_id == user_id]
        context_clauses = []
        if conversation_id is not None:
            context_clauses.append(Memory.conversation_id == conversation_id)
        if job_id is not None:
            context_clauses.append(Memory.job_id == job_id)

        if context_clauses:
            # 先检索当前上下文相关
            context_result = await self.session.execute(
                select(
                    Memory,
                    Memory.embedding.cosine_distance(query_vector).label("distance"),
                )
                .where(and_(*clauses, or_(*context_clauses)))
                .order_by("distance")
                .limit(limit)
            )
            context_items = [(row.Memory, row.distance) for row in context_result.all()]
            remaining = limit - len(context_items)
            if remaining <= 0:
                return context_items

            # 再补全局记忆（排除已返回的）
            existing_ids = {m.id for m, _ in context_items}
            global_result = await self.session.execute(
                select(
                    Memory,
                    Memory.embedding.cosine_distance(query_vector).label("distance"),
                )
                .where(
                    and_(
                        *clauses,
                        ~Memory.id.in_(existing_ids),
                        Memory.conversation_id.is_(None),
                        Memory.job_id.is_(None),
                    )
                )
                .order_by("distance")
                .limit(remaining)
            )
            global_items = [(row.Memory, row.distance) for row in global_result.all()]
            return context_items + global_items

        # 无上下文限定，直接全局检索
        return await self.semantic_search(user_id, query_vector, limit)
