"""岗位 Repository。"""

from __future__ import annotations

from sqlalchemy import and_, select

from app.models.job import Job
from app.repository.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    """岗位数据访问层。"""

    model = Job

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
