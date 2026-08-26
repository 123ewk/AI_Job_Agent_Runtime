"""长期记忆 Repository。"""

from __future__ import annotations

from sqlalchemy import and_, or_, select

from app.models.memory import Memory
from app.repository.base import BaseRepository

# 未配置向量模型时写入的占位零向量（满足 memory.embedding NOT NULL 约束）。
# 语义检索用 `!=` 排除历史占位行——零向量余弦距离为 NaN，若不排除会污染
# 检索排序（相似度 NaN 恒 < 阈值，去重/排序全失效）。
ZERO_EMBEDDING: list[float] = [0.0] * 512


class MemoryRepository(BaseRepository[Memory]):
    """长期记忆数据访问层。

    支持按类型、关联会话/岗位过滤，以及向量语义检索。
    未配置向量模型时走关键词 / 精确内容 / 时间倒序降级路径。
    """

    model = Memory

    def _filters(
        self,
        user_id: int,
        conversation_id: int | None = None,
        job_id: int | None = None,
        memory_type: str | None = None,
    ) -> list[object]:
        """构建通用过滤条件（语义检索与降级检索复用，避免条件漂移）。"""
        clauses: list[object] = [Memory.user_id == user_id]
        if conversation_id is not None:
            clauses.append(Memory.conversation_id == conversation_id)
        if job_id is not None:
            clauses.append(Memory.job_id == job_id)
        if memory_type is not None:
            clauses.append(Memory.type == memory_type)
        return clauses

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

        排除零向量占位行：未配置向量模型时期写入的占位数据余弦距离为 NaN，
        必须过滤，否则污染排序（相似度 NaN 恒 < 阈值，去重/排序全失效）。
        """
        clauses = self._filters(user_id, conversation_id, job_id, memory_type)
        # 排除历史占位零向量行，防止旧占位数据污染新语义检索
        clauses.append(Memory.embedding != ZERO_EMBEDDING)

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

    async def find_by_content_exact(
        self,
        user_id: int,
        content: str,
        memory_type: str | None = None,
    ) -> Memory | None:
        """精确内容去重（降级路径：未配置向量模型时替代语义去重）。

        相同 content 命中即视为重复，返回最近一条。
        """
        clauses: list[object] = [Memory.user_id == user_id, Memory.content == content]
        if memory_type is not None:
            clauses.append(Memory.type == memory_type)
        result = await self.session.execute(
            select(Memory).where(and_(*clauses)).order_by(Memory.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def search_keyword(  # noqa: PLR0917
        self,
        user_id: int,
        keyword: str,
        limit: int = 10,
        conversation_id: int | None = None,
        job_id: int | None = None,
        memory_type: str | None = None,
    ) -> list[Memory]:
        """关键词检索（降级路径：未配置向量模型时替代语义检索）。

        对 content 做 ILIKE 模糊匹配，按创建时间倒序（最新优先）。
        用户输入零信任：转义 % _ 通配符，防止超范围匹配（如用户搜「100%」）。
        """
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses = self._filters(user_id, conversation_id, job_id, memory_type)
        clauses.append(Memory.content.ilike(f"%{escaped}%", escape="\\"))
        result = await self.session.execute(
            select(Memory).where(and_(*clauses)).order_by(Memory.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_recent(self, user_id: int, limit: int = 10) -> list[Memory]:
        """最近记忆（降级路径：任务上下文无向量可用时按时间倒序取最近）。"""
        result = await self.session.execute(
            select(Memory)
            .where(Memory.user_id == user_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

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
        # 排除历史占位零向量行（与 semantic_search 同规，防 NaN 污染）
        zero_guard = [Memory.embedding != ZERO_EMBEDDING]

        if context_clauses:
            # 先检索当前上下文相关
            context_result = await self.session.execute(
                select(
                    Memory,
                    Memory.embedding.cosine_distance(query_vector).label("distance"),
                )
                .where(and_(*clauses, *zero_guard, or_(*context_clauses)))
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
                        *zero_guard,
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
