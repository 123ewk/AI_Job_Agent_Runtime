"""简历 Repository。"""

from __future__ import annotations

from sqlalchemy import and_, select

from app.models.resume import Resume
from app.repository.base import BaseRepository


class ResumeRepository(BaseRepository[Resume]):
    """简历数据访问层。

    Resume 存元数据 + 文件引用（MinIO key/url），
    文本摘要 + embedding 存在 ResumeSummary（支持多版本）。
    """

    model = Resume

    async def get_default(self, user_id: int) -> Resume | None:
        """获取用户默认简历（投递用）。"""
        result = await self.session.execute(
            select(Resume).where(
                and_(Resume.user_id == user_id, Resume.is_default.is_(True))  # type: ignore[attr-defined]
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int, limit: int = 20) -> list[Resume]:
        """列出用户所有简历（含已归档）。"""
        return await self.list_by_filter(
            {"user_id": user_id},
            order_by="updated_at",
            limit=limit,
        )
