"""HR Repository。"""

from __future__ import annotations

from sqlalchemy import select

from app.models.hr import HR
from app.repository.base import BaseRepository


class HRRepository(BaseRepository[HR]):
    """HR 数据访问层。"""

    model = HR

    async def get_by_external_id(self, platform: str, external_id: str, user_id: int) -> HR | None:
        """按平台外部 ID 查找 HR（同步去重用）。"""
        return await self.get_by_unique(user_id=user_id, platform=platform, external_id=external_id)

    async def list_by_user(self, user_id: int, platform: str | None = None) -> list[HR]:
        """按用户列出 HR，可选按平台过滤。"""
        filters = {"user_id": user_id}
        if platform is not None:
            filters["platform"] = platform
        return await self.list_by_filter(filters)

    async def search_by_name(self, user_id: int, name_keyword: str) -> list[HR]:
        """按姓名关键词搜索 HR（模糊匹配）。"""
        result = await self.session.execute(
            select(HR).where(
                HR.user_id == user_id,
                HR.name.ilike(f"%{name_keyword}%"),
            )
        )
        return list(result.scalars().all())
