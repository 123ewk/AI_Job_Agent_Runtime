"""用户 Repository。"""

from __future__ import annotations

from sqlalchemy import select

from app.models.user import User
from app.repository.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """用户数据访问层。

    注意：密码哈希、LLM API Key 加密等业务逻辑放在 Service 层，此处只做 DB 操作。
    """

    model = User

    async def get_by_email(self, email: str) -> User | None:
        """按邮箱查询（登录/去重用）。"""
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
