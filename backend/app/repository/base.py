"""Repository 基类（数据访问层，doc 02 分层架构）。

Repository 层封装 DB 操作，Service 层不直接操作 Session。
核心设计：
- 泛型基类，各领域 Repository 继承扩展
- 游标分页，避免 OFFSET 深翻性能问题
- selectinload / joinedload 预加载防 N+1
- 统一异常边界（DB 层异常不向上泄露原始 SQLAlchemy 异常）

依赖方向：
    repository -> model -> db
    （反向依赖禁止：model 不能 import repository）
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, Literal, TypeVar

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, selectinload
from sqlalchemy.sql.selectable import Select

from app.db.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """泛型 Repository 基类。

    继承示例::

        class UserRepository(BaseRepository[User]):
            model = User
            # 扩展 User 专属查询方法
    """

    model: type[T]

    def __init__(self, session: AsyncSession) -> None:
        """通过依赖注入获取 Session，确保每个请求独立会话。"""
        self.session = session

    # ---------------------------------------------------------------------
    # 基础 CRUD
    # ---------------------------------------------------------------------

    async def get(self, id: int) -> T | None:
        """按主键 id 获取单条记录。"""
        result = await self.session.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_by_ids(self, ids: Sequence[int]) -> list[T]:
        """批量按主键获取，返回顺序与 ids 顺序一致。"""
        if not ids:
            return []
        result = await self.session.execute(select(self.model).where(self.model.id.in_(ids)))
        items = result.scalars().all()
        # 按传入 id 排序保序
        id_map = {item.id: item for item in items}  # type: ignore[attr-defined]
        return [id_map[id] for id in ids if id in id_map]

    async def create(self, data: dict[str, Any]) -> T:
        """创建记录。

        事务边界由 Service 层控制（@transactional），本方法只负责入 session 并 flush。
        flush 而非 commit：把 INSERT 发到当前事务，使自增 id 与 server_default
        （created_at / status 默认值等）立即回填到对象，调用方据此构造 Response；
        真正的 commit 仍由外层 @transactional 在方法返回后执行。
        """
        obj = self.model(**data)
        self.session.add(obj)
        # 触发 INSERT（RETURNING 回填自增主键与 server_default），保证调用方能读到 id 等字段
        await self.session.flush()
        return obj

    async def update(self, id: int, data: dict[str, Any]) -> T | None:
        """按主键更新，只更新指定字段（partial update）。"""
        if not data:
            return await self.get(id)
        await self.session.execute(
            update(self.model).where(self.model.id == id).values(**data)
        )
        return await self.get(id)

    async def delete(self, id: int) -> bool:
        """按主键删除，返回是否实际删除了记录。"""
        result = await self.session.execute(delete(self.model).where(self.model.id == id))
        deleted_count = result.rowcount  # type: ignore[attr-defined]
        return bool(deleted_count)

    # ---------------------------------------------------------------------
    # 列表查询与分页
    # ---------------------------------------------------------------------

    async def list_all(self, order_by: str = "id", limit: int | None = None) -> list[T]:
        """全量列表（小表用；大表必须分页）。"""
        stmt = select(self.model).order_by(order_by)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        """总记录数（供前端分页展示）。"""
        result = await self.session.execute(select(func.count(self.model.id)))
        return result.scalar_one()

    async def paginate(
        self,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "id",
        order_dir: Literal["asc", "desc"] = "desc",
    ) -> tuple[list[T], int]:
        """OFFSET 分页（仅用于管理后台小数据量；大数据量改用 cursor_paginate）。

        page 从 1 开始；返回 (items, total_count)。
        """
        order_clause = (
            self.model.__table__.c[order_by].asc()  # type: ignore[index]
            if order_dir == "asc"
            else self.model.__table__.c[order_by].desc()
        )
        stmt = select(self.model).order_by(order_clause)
        count_stmt = select(func.count(self.model.id))

        total = (await self.session.execute(count_stmt)).scalar_one()
        if page >= 1:
            stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        items = (await self.session.execute(stmt)).scalars().all()
        return list(items), total

    async def cursor_paginate(
        self,
        last_id: int | None = None,
        page_size: int = 20,
        order_by: str = "id",
    ) -> list[T]:
        """游标分页（推荐，避免 OFFSET 深翻性能退化）。

        last_id 为上一页最后一条的 id；首次传 None 从头部开始。
        注意：cursor 分页要求排序字段有索引且单调（id 最佳）。
        """
        order_clause = self.model.__table__.c[order_by].desc()  # type: ignore[index]
        stmt = select(self.model).order_by(order_clause)

        if last_id is not None:
            cursor_col = self.model.__table__.c[order_by]  # type: ignore[index]
            stmt = stmt.where(cursor_col < last_id)

        stmt = stmt.limit(page_size)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ---------------------------------------------------------------------
    # 预加载（防 N+1）
    # ---------------------------------------------------------------------

    def _apply_selectinload(
        self,
        stmt: Select,
        relationships: Sequence[QueryableAttribute[Any]],
    ) -> Select:
        """给 Query 加上 selectinload 预加载。

        selectinload：1+N 发 2 条查询（主表 + IN 子查询查关联），
        适合 one-to-many / many-to-many。

        例::

            # User.resumes 一对多关系
            stmt = self._apply_selectinload(stmt, [User.resumes])
        """
        for rel in relationships:
            stmt = stmt.options(selectinload(rel))
        return stmt

    # ---------------------------------------------------------------------
    # 基础条件查询
    # ---------------------------------------------------------------------

    async def get_by_unique(self, **filters: object) -> T | None:
        """按唯一键获取单条记录。

        例::

            await repo.get_by_unique(email="user@example.com")
        """
        clauses = [getattr(self.model, k) == v for k, v in filters.items()]
        result = await self.session.execute(select(self.model).where(and_(*clauses)))
        return result.scalar_one_or_none()

    async def list_by_filter(
        self,
        filters: dict[str, Any],
        order_by: str = "id",
        limit: int | None = None,
        *,
        skip: int = 0,
    ) -> list[T]:
        """按等值条件过滤列表（多条件 AND 关系）。"""
        clauses = [getattr(self.model, k) == v for k, v in filters.items()]
        order_clause = self.model.__table__.c[order_by].desc()  # type: ignore[index]
        stmt = select(self.model).where(and_(*clauses)).order_by(order_clause)
        if skip > 0:
            stmt = stmt.offset(skip)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_filter(self, filters: dict[str, Any]) -> int:
        """按等值条件统计数量（多条件 AND 关系）。"""
        clauses = [getattr(self.model, k) == v for k, v in filters.items()]
        stmt = select(func.count(self.model.id)).where(and_(*clauses))
        result = await self.session.execute(stmt)
        count: int = result.scalar_one()
        return count

    async def list_by_filter_with_count(
        self,
        filters: dict[str, Any],
        page: int = 1,
        page_size: int = 20,
        order_by: str = "id",
    ) -> tuple[list[T], int]:
        """按等值条件过滤并分页，同时返回总数。"""
        clauses = [getattr(self.model, k) == v for k, v in filters.items()]
        order_clause = self.model.__table__.c[order_by].desc()  # type: ignore[index]

        count_stmt = select(func.count(self.model.id)).where(and_(*clauses))
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = select(self.model).where(and_(*clauses)).order_by(order_clause)
        if page >= 1:
            stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        items = (await self.session.execute(stmt)).scalars().all()

        return list(items), total

    async def get_for_update(self, id: int) -> T | None:
        """按主键获取并加行锁（FOR UPDATE）。

        用于需要原子更新状态的场景（如状态流转、库存扣减）。
        注意：必须在事务内调用，否则锁立即释放。
        """
        result = await self.session.execute(
            select(self.model).where(self.model.id == id).with_for_update()  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none()
