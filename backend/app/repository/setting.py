"""用户配置 Repository。"""

from __future__ import annotations

from sqlalchemy import and_, select

from app.models.setting import Setting
from app.repository.base import BaseRepository


class SettingRepository(BaseRepository[Setting]):
    """用户配置数据访问层。

    category 与 API 域一一对应：llm / job_rule / agent / reply_style。
    """

    model = Setting

    async def get_by_user_and_category(self, user_id: int, category: str) -> list[Setting]:
        """按用户 + 配置域获取所有配置项。"""
        result = await self.session.execute(
            select(Setting).where(
                and_(
                    Setting.user_id == user_id,
                    Setting.category == category,
                )
            )
        )
        return list(result.scalars().all())

    async def get_by_key(self, user_id: int, category: str, key: str) -> Setting | None:
        """按唯一键获取具体配置项。"""
        return await self.get_by_unique(user_id=user_id, category=category, key=key)

    async def list_by_user(self, user_id: int) -> list[Setting]:
        """获取用户的所有配置。"""
        return await self.list_by_filter({"user_id": user_id})
