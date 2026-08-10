"""简历摘要 Repository。"""

from __future__ import annotations

from sqlalchemy import desc, select

from app.models.resume_summary import ResumeSummary
from app.repository.base import BaseRepository


class ResumeSummaryRepository(BaseRepository[ResumeSummary]):
    """简历摘要与向量数据访问层。"""

    model = ResumeSummary

    async def get_latest_by_resume_id(self, resume_id: int) -> ResumeSummary | None:
        """获取简历的最新版本摘要。"""
        result = await self.session.execute(
            select(ResumeSummary)
            .where(ResumeSummary.resume_id == resume_id)
            .order_by(desc(ResumeSummary.version))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_version(self, resume_id: int, version: int) -> ResumeSummary | None:
        """按简历 ID + 版本号获取摘要。"""
        return await self.get_by_unique(resume_id=resume_id, version=version)

    async def list_by_resume_id(self, resume_id: int) -> list[ResumeSummary]:
        """列出简历的所有历史版本摘要。"""
        return await self.list_by_filter({"resume_id": resume_id}, order_by="version")

    async def semantic_search(
        self,
        resume_id: int,
        query_vector: list[float],
        limit: int = 5,
    ) -> list[tuple[ResumeSummary, float]]:
        """语义相似度检索（基于 embedding 向量余弦距离）。

        返回 (summary, distance) 对，按相似度排序。
        """
        result = await self.session.execute(
            select(
                ResumeSummary,
                ResumeSummary.embedding.cosine_distance(query_vector).label("distance"),
            )
            .where(ResumeSummary.resume_id == resume_id)
            .order_by("distance")
            .limit(limit)
        )
        return [(row.ResumeSummary, row.distance) for row in result.all()]
