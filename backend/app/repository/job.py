"""岗位 Repository。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select

from app.models.job import Job
from app.repository.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    """岗位数据访问层。"""

    model = Job

    async def list_with_search(
        self,
        filters: dict[str, Any],
        keyword: str | None = None,
        min_score: float | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Job], int]:
        """等值过滤 + keyword（ILIKE title/company）+ min_score（>=）组合查询。

        base 的 list_by_filter_with_count 只支持等值过滤，无法表达
        文本模糊匹配与数值范围，故在此扩展。分页契约与其保持一致。

        注意：keyword 的 %xx% 通配使 ILIKE 无法走 B-tree 索引（全表扫描），
        当前数据量下可接受；量级上来后需引入 pg_trgm 或全文检索。
        """
        clauses = [getattr(Job, k) == v for k, v in filters.items()]
        if keyword:
            pattern = f"%{keyword}%"
            # title/company 均可空，ILIKE 对 NULL 自然不匹配，无需额外判空
            clauses.append(or_(Job.title.ilike(pattern), Job.company.ilike(pattern)))
        if min_score is not None:
            clauses.append(Job.score >= min_score)

        count_stmt = select(func.count(Job.id)).where(and_(*clauses))
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = select(Job).where(and_(*clauses)).order_by(Job.id.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        items = (await self.session.execute(stmt)).scalars().all()
        return list(items), total

    async def get_by_platform_external(self, platform: str, external_id: str) -> Job | None:
        """按平台 + 外部 ID 定位（同步/去重用）。"""
        result = await self.session.execute(
            select(Job).where(
                and_(
                    Job.platform == platform,
                    Job.external_id == external_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_status(self, status: str, limit: int = 100) -> list[Job]:
        """按状态过滤岗位列表。"""
        return await self.list_by_filter({"status": status}, limit=limit)

    async def count_by_user(self, user_id: int) -> int:
        """统计用户岗位总数（用户统计信息用）。

        count_by_filter 只发 COUNT 聚合，比 list_by_filter 取全量再 len 更省。
        """
        return await self.count_by_filter({"user_id": user_id})
