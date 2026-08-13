"""ResumeService 单元测试。

职责：不连数据库，mock 掉 ResumeRepository，直接验证 Service 层业务分支：
- create 首个简历自动 is_default=True / version=1 / 注入 user_id
- get 命中与 NotFoundError
- list 按 user_id 过滤 + 分页组装
- set_default 先 clear_default 再置当前（唯一性）
- delete 命中与 NotFoundError

@transactional 处理与 test_job_service.py 一致：db 用 AsyncMock，但覆盖
in_transaction 为同步返回 False、begin/begin_nested 为 async context manager。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError
from app.models.resume import Resume
from app.repository.resume import ResumeRepository
from app.schema.resume import ResumeCreate
from app.service.resume import ResumeService


class _AsyncContextManager:
    """async 上下文管理器替身，替代 db.begin() 的 `async with` 行为。"""

    async def __aenter__(self) -> _AsyncContextManager:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def _make_resume(**overrides: object) -> Resume:
    """构造 Resume ORM 实例。

    created_at/updated_at 必须显式传：Model 上只有 server_default，Python 侧
    构造不会回填；而 ResumeResponse 两个字段必填，缺了 model_validate 会失败。
    """
    base = datetime(2026, 8, 1, tzinfo=UTC)
    defaults: dict[str, Any] = {
        "id": 1,
        "user_id": 1,
        "name": "我的简历",
        "version": 1,
        "status": "active",
        "is_default": False,
        "content": "姓名：张三\n技能：Python、FastAPI",
        "created_at": base,
        "updated_at": base,
    }
    defaults.update(overrides)
    return Resume(**defaults)


@pytest.fixture
def db() -> AsyncMock:
    """mock AsyncSession：只满足 @transactional 对 in_transaction/begin 的调用。"""
    session = AsyncMock()
    session.in_transaction = MagicMock(return_value=False)
    session.begin = MagicMock(return_value=_AsyncContextManager())
    session.begin_nested = MagicMock(return_value=_AsyncContextManager())
    return session


@pytest.fixture
def service(db: AsyncMock) -> ResumeService:
    """构造 ResumeService，Repository 替换为 AsyncMock（不连 DB）。"""
    svc = ResumeService(db)
    svc.resume_repo = AsyncMock(spec=ResumeRepository)
    return svc


class TestResumeCreate:
    """create：首个简历设默认。"""

    async def test_create_first_resume_is_default(self, service: ResumeService) -> None:
        """用户无简历：自动 is_default=True，version=1，注入 user_id。"""
        service.resume_repo.count_by_filter.return_value = 0
        created = _make_resume(id=1, name="我的简历", is_default=True, version=1)
        service.resume_repo.create.return_value = created

        result = await service.create(user_id=1, data=ResumeCreate(name="我的简历", content="技能：Python"))

        assert result.id == 1
        assert result.is_default is True
        assert result.version == 1
        service.resume_repo.count_by_filter.assert_awaited_once_with({"user_id": 1})
        service.resume_repo.create.assert_awaited_once()
        call_data = service.resume_repo.create.await_args.args[0]
        assert call_data["user_id"] == 1
        assert call_data["is_default"] is True
        assert call_data["version"] == 1
        # content 透传
        assert call_data["content"] == "技能：Python"

    async def test_create_non_first_resume_not_default(self, service: ResumeService) -> None:
        """用户已有简历：新建简历默认非默认。"""
        service.resume_repo.count_by_filter.return_value = 2
        created = _make_resume(id=2, name="第二份", is_default=False)
        service.resume_repo.create.return_value = created

        result = await service.create(user_id=1, data=ResumeCreate(name="第二份", content="x"))

        assert result.is_default is False
        call_data = service.resume_repo.create.await_args.args[0]
        assert call_data["is_default"] is False


class TestResumeGet:
    """get：命中与未命中。"""

    async def test_get_found(self, service: ResumeService) -> None:
        """记录存在：返回 ResumeDetailResponse，含解析原文。"""
        service.resume_repo.get_by_unique.return_value = _make_resume(id=5, content="简历正文")

        result = await service.get(user_id=1, resume_id=5)

        assert result.id == 5
        assert result.content == "简历正文"
        service.resume_repo.get_by_unique.assert_awaited_once_with(id=5, user_id=1)

    async def test_get_not_found_raises(self, service: ResumeService) -> None:
        """记录不存在：抛 NotFoundError。"""
        service.resume_repo.get_by_unique.return_value = None

        with pytest.raises(NotFoundError):
            await service.get(user_id=1, resume_id=999)


class TestResumeList:
    """list：按 user_id 过滤 + 分页。"""

    async def test_list_paginates(self, service: ResumeService) -> None:
        """组装分页响应，filters 恒含 user_id。"""
        service.resume_repo.list_by_filter_with_count.return_value = (
            [_make_resume(id=1), _make_resume(id=2)],
            2,
        )

        result = await service.list(user_id=1, page=2, page_size=10)

        service.resume_repo.list_by_filter_with_count.assert_awaited_once()
        assert service.resume_repo.list_by_filter_with_count.await_args.args[0] == {"user_id": 1}
        kwargs = service.resume_repo.list_by_filter_with_count.await_args.kwargs
        assert kwargs["page"] == 2
        assert kwargs["page_size"] == 10
        assert result.total == 2
        assert result.page == 2
        assert len(result.items) == 2


class TestResumeSetDefault:
    """set_default：先清空再置顶，保证唯一性。"""

    async def test_set_default_clears_then_sets(self, service: ResumeService) -> None:
        """先 clear_default(user_id)，再 update 当前简历 is_default=True。"""
        service.resume_repo.get_by_unique.side_effect = [
            _make_resume(id=1, is_default=False),  # 首次调用：存在性校验
            _make_resume(id=1, is_default=True),  # 二次调用：更新后回读
        ]

        result = await service.set_default(user_id=1, resume_id=1)

        assert result.is_default is True
        service.resume_repo.clear_default.assert_awaited_once_with(1)
        service.resume_repo.update.assert_awaited_once()
        rid, data = service.resume_repo.update.await_args.args
        assert rid == 1
        assert data == {"is_default": True}

    async def test_set_default_not_found_raises(self, service: ResumeService) -> None:
        """简历不存在：抛 NotFoundError，且不执行 clear/update。"""
        service.resume_repo.get_by_unique.return_value = None

        with pytest.raises(NotFoundError):
            await service.set_default(user_id=1, resume_id=999)

        service.resume_repo.clear_default.assert_not_awaited()
        service.resume_repo.update.assert_not_awaited()


class TestResumeDelete:
    """delete：命中与未命中。"""

    async def test_delete_success(self, service: ResumeService) -> None:
        """删除命中：调用 repo.delete。"""
        service.resume_repo.get_by_unique.return_value = _make_resume(id=1)

        await service.delete(user_id=1, resume_id=1)

        service.resume_repo.delete.assert_awaited_once_with(1)

    async def test_delete_not_found_raises(self, service: ResumeService) -> None:
        """删除不存在：抛 NotFoundError。"""
        service.resume_repo.get_by_unique.return_value = None

        with pytest.raises(NotFoundError):
            await service.delete(user_id=1, resume_id=999)

        service.resume_repo.delete.assert_not_awaited()
