"""JobService 单元测试。

职责：不连数据库，mock 掉 JobRepository / HRRepository / AsyncSession，
直接验证 Service 层的业务逻辑分支：
- create 去重（同 platform + external_id 已存在则直接返回既有记录，不重复创建）
- list 的分支选择（keyword/min_score 走 list_with_search，否则 list_by_filter_with_count）
- 筛选字典组装（status 枚举转字符串、platform 透传、user_id 恒注入）
- create_hr / list_hr 的去重与分页
- NotFoundError 异常路径（get/update/delete 不存在记录）

为什么不用 test_jobs_api.py 的方式：
- API 集成测试已覆盖「HTTP -> Service -> 真实 PG」全链路（75 passed）
- 但「去重时 create 是否被调用」「list 到底走了哪个 repo 方法」「filter 字典如何拼」
  这类行为在 HTTP 层无法精确断言；mock 掉 repo 后可逐条验证。

@transactional 处理：
- create/update/delete/create_hr 挂了事务装饰器，会调用 db.in_transaction() 与
  db.begin()。db 用 AsyncMock，但 in_transaction 覆盖为同步返回 False（否则
  AsyncMock 会把它变成 async，返回协程对象恒为真，装饰器会误判「已在事务中」
  走 savepoint 分支）；begin 覆盖为 async context manager。全程不触碰真数据库。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError
from app.models.hr import HR
from app.models.job import Job
from app.repository.hr import HRRepository
from app.repository.job import JobRepository
from app.schema.enums import JobStatus
from app.schema.job import HRCreate, JobCreate, JobFilterParams, JobUpdate
from app.service.job import JobService


class _AsyncContextManager:
    """async 上下文管理器替身，替代 db.begin() 的 `async with` 行为。"""

    async def __aenter__(self) -> _AsyncContextManager:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def _make_job(**overrides: object) -> Job:
    """构造 Job ORM 实例。

    created_at/updated_at 必须显式传：Model 上只有 server_default，Python 侧
    构造不会回填；而 JobResponse 两个字段必填，缺了 model_validate 会失败。
    """
    base = datetime(2026, 8, 1, tzinfo=UTC)
    defaults: dict[str, Any] = {
        "id": 1,
        "user_id": 1,
        "platform": "boss",
        "external_id": "job-001",
        "title": "Python 后端工程师",
        "company": "测试公司",
        "salary": "20-40k",
        "location": "北京",
        "status": "discovered",
        "created_at": base,
        "updated_at": base,
    }
    defaults.update(overrides)
    return Job(**defaults)


def _make_hr(**overrides: object) -> HR:
    """构造 HR ORM 实例（同理显式传时间戳）。"""
    base = datetime(2026, 8, 1, tzinfo=UTC)
    defaults: dict[str, Any] = {
        "id": 1,
        "user_id": 1,
        "platform": "boss",
        "external_id": "hr-001",
        "name": "张经理",
        "company": "ACME",
        "position": "招聘",
        "created_at": base,
        "updated_at": base,
    }
    defaults.update(overrides)
    return HR(**defaults)


@pytest.fixture
def db() -> AsyncMock:
    """mock AsyncSession：只满足 @transactional 对 in_transaction/begin 的调用。

    in_transaction() 在真 AsyncSession 上是同步方法；AsyncMock 会把所有方法
    变 async，调用返回协程对象恒为真——装饰器会误判「已在事务中」而走 savepoint
    分支。故显式覆盖为同步 MagicMock 返回 False，走最外层真实事务分支。
    """
    session = AsyncMock()
    session.in_transaction = MagicMock(return_value=False)
    session.begin = MagicMock(return_value=_AsyncContextManager())
    session.begin_nested = MagicMock(return_value=_AsyncContextManager())
    return session


@pytest.fixture
def service(db: AsyncMock) -> JobService:
    """构造 JobService，Repository 替换为 AsyncMock（不连 DB）。

    spec=... 限定 mock 只能出现 Repository 上真实存在的属性，防手误。
    """
    svc = JobService(db)
    svc.job_repo = AsyncMock(spec=JobRepository)
    svc.hr_repo = AsyncMock(spec=HRRepository)
    return svc


class TestJobCreate:
    """create：去重与新建两条路径。"""

    async def test_create_dedup_returns_existing(self, service: JobService) -> None:
        """同 platform + external_id 已存在：返回既有记录且不再创建。"""
        existing = _make_job(id=10, external_id="dup-1", title="已存在职位")
        service.job_repo.get_by_platform_external.return_value = existing

        result = await service.create(user_id=1, data=JobCreate(external_id="dup-1"))

        assert result.id == 10
        assert result.title == "已存在职位"
        service.job_repo.get_by_platform_external.assert_awaited_once_with("boss", "dup-1")
        service.job_repo.create.assert_not_awaited()

    async def test_create_new_injects_user_id(self, service: JobService) -> None:
        """不存在记录：注入 user_id 后创建，返回新职位。"""
        service.job_repo.get_by_platform_external.return_value = None
        created = _make_job(id=11, external_id="new-1", user_id=7)
        service.job_repo.create.return_value = created

        result = await service.create(user_id=7, data=JobCreate(external_id="new-1", title="Python 工程师"))

        assert result.id == 11
        assert result.user_id == 7
        service.job_repo.create.assert_awaited_once()
        call_data = service.job_repo.create.await_args.args[0]
        assert call_data["user_id"] == 7
        assert call_data["external_id"] == "new-1"


class TestJobGet:
    """get_by_id：命中与未命中。"""

    async def test_get_by_id_found(self, service: JobService) -> None:
        """记录存在：返回 JobResponse。"""
        service.job_repo.get_by_unique.return_value = _make_job(id=5)

        result = await service.get_by_id(user_id=1, job_id=5)

        assert result.id == 5
        service.job_repo.get_by_unique.assert_awaited_once_with(id=5, user_id=1)

    async def test_get_by_id_not_found_raises(self, service: JobService) -> None:
        """记录不存在：抛 NotFoundError。"""
        service.job_repo.get_by_unique.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_by_id(user_id=1, job_id=999)


class TestJobList:
    """list：分支选择（search vs 普通分页）与筛选字典组装。"""

    async def test_list_uses_plain_filter_without_search(self, service: JobService) -> None:
        """无 keyword/min_score：走 list_by_filter_with_count，status 枚举转字符串。"""
        jobs = [_make_job(id=1), _make_job(id=2)]
        service.job_repo.list_by_filter_with_count.return_value = (jobs, 2)

        result = await service.list(
            user_id=1,
            filters=JobFilterParams(status=JobStatus.SCORED, platform="boss"),
            page=2,
            page_size=10,
        )

        service.job_repo.list_by_filter_with_count.assert_awaited_once()
        kwargs = service.job_repo.list_by_filter_with_count.await_args.kwargs
        assert kwargs["filters"] == {"user_id": 1, "status": "scored", "platform": "boss"}
        assert kwargs["page"] == 2
        assert kwargs["page_size"] == 10
        assert result.total == 2
        assert result.page == 2
        assert len(result.items) == 2
        service.job_repo.list_with_search.assert_not_awaited()

    async def test_list_uses_search_when_keyword(self, service: JobService) -> None:
        """keyword 非空：走 list_with_search（含 ILIKE 的扩展查询）。"""
        service.job_repo.list_with_search.return_value = ([_make_job(id=1, title="Python 后端")], 1)

        result = await service.list(user_id=1, filters=JobFilterParams(keyword="Python"))

        service.job_repo.list_with_search.assert_awaited_once()
        kwargs = service.job_repo.list_with_search.await_args.kwargs
        assert kwargs["keyword"] == "Python"
        assert kwargs["min_score"] is None
        assert kwargs["page"] == 1
        assert kwargs["page_size"] == 20
        assert result.total == 1
        service.job_repo.list_by_filter_with_count.assert_not_awaited()

    async def test_list_uses_search_when_min_score(self, service: JobService) -> None:
        """min_score 非空同样走 search 分支（score >= 过滤）。"""
        service.job_repo.list_with_search.return_value = ([_make_job(id=1, score=0.8)], 1)

        result = await service.list(user_id=1, filters=JobFilterParams(min_score=0.5))

        service.job_repo.list_with_search.assert_awaited_once()
        assert result.total == 1
        assert result.items[0].score == 0.8


class TestJobUpdateDelete:
    """update/delete：命中与未命中。"""

    async def test_update_success(self, service: JobService) -> None:
        """部分更新：透传 update_data 给 repo，返回更新后的响应。"""
        service.job_repo.get_by_unique.return_value = _make_job(id=1)
        updated = _make_job(id=1, title="高级 Python", status="scored")
        service.job_repo.update.return_value = updated

        result = await service.update(user_id=1, job_id=1, data=JobUpdate(title="高级 Python", status=JobStatus.SCORED))

        assert result.title == "高级 Python"
        assert result.status == "scored"
        service.job_repo.update.assert_awaited_once()
        call_id, call_data = service.job_repo.update.await_args.args
        assert call_id == 1
        assert call_data["title"] == "高级 Python"

    async def test_update_not_found_raises(self, service: JobService) -> None:
        """更新不存在的职位：抛 NotFoundError。"""
        service.job_repo.get_by_unique.return_value = None

        with pytest.raises(NotFoundError):
            await service.update(user_id=1, job_id=999, data=JobUpdate(title="x"))

    async def test_delete_not_found_raises(self, service: JobService) -> None:
        """删除不存在的职位：抛 NotFoundError。"""
        service.job_repo.get_by_unique.return_value = None

        with pytest.raises(NotFoundError):
            await service.delete(user_id=1, job_id=999)


class TestHR:
    """create_hr / list_hr。"""

    async def test_create_hr_dedup_returns_existing(self, service: JobService) -> None:
        """同 (user_id, platform, external_id) 已存在：返回既有 HR，不重复创建。"""
        existing = _make_hr(id=3, external_id="hr-dup")
        service.hr_repo.get_by_external_id.return_value = existing

        result = await service.create_hr(user_id=1, data=HRCreate(external_id="hr-dup"))

        assert result.id == 3
        service.hr_repo.get_by_external_id.assert_awaited_once_with("boss", "hr-dup", 1)
        service.hr_repo.create.assert_not_awaited()

    async def test_create_hr_new_injects_user_id(self, service: JobService) -> None:
        """不存在：注入 user_id 后创建。"""
        service.hr_repo.get_by_external_id.return_value = None
        created = _make_hr(id=4, user_id=1)
        service.hr_repo.create.return_value = created

        result = await service.create_hr(user_id=1, data=HRCreate(external_id="hr-new", name="李主管"))

        service.hr_repo.create.assert_awaited_once()
        call_data = service.hr_repo.create.await_args.args[0]
        assert call_data["user_id"] == 1
        assert call_data["external_id"] == "hr-new"
        assert result.id == 4

    async def test_list_hr_paginates(self, service: JobService) -> None:
        """list_hr：按 user_id 过滤并组装分页响应。"""
        service.hr_repo.list_by_filter_with_count.return_value = ([_make_hr(id=1), _make_hr(id=2)], 2)

        result = await service.list_hr(user_id=1, page=1, page_size=50)

        service.hr_repo.list_by_filter_with_count.assert_awaited_once()
        # service 以位置参数传 filters：{"user_id": user_id}
        assert service.hr_repo.list_by_filter_with_count.await_args.args[0] == {"user_id": 1}
        kwargs = service.hr_repo.list_by_filter_with_count.await_args.kwargs
        assert kwargs["page"] == 1
        assert kwargs["page_size"] == 50
        assert result.total == 2
        assert len(result.items) == 2
