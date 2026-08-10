"""BaseRepository 方法集成测试。

重点测试分页、过滤、计数等通用方法。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job
from app.repository import JobRepository


class TestBaseRepository:
    """BaseRepository 通用方法测试集。"""

    @pytest.fixture
    def job_repo(self, test_session: AsyncSession) -> JobRepository:
        """JobRepository 实例。"""
        return JobRepository(test_session)

    @pytest.fixture
    async def seed_user(self, test_session: AsyncSession) -> int:
        """植入测试用户。"""
        from app.models import User
        user = User(email="test@example.com")
        test_session.add(user)
        await test_session.flush()
        await test_session.commit()
        return user.id

    @pytest.fixture
    async def seed_jobs(self, test_session: AsyncSession, seed_user: int) -> list[Job]:
        """植入测试数据。"""
        jobs = [
            Job(
                user_id=seed_user,
                title=f"职位{i}",
                company=f"公司{i}",
                platform="boss",
                external_id=f"job_{i}",
                status="active" if i % 2 == 0 else "applied",
                salary=f"{20000 + i * 1000}-{30000 + i * 1000}",
                location="北京" if i < 5 else "上海",
            )
            for i in range(10)
        ]
        test_session.add_all(jobs)
        await test_session.commit()
        return jobs

    async def test_list_by_filter_with_count_basic(
        self,
        job_repo: JobRepository,
        seed_jobs: list[Job],
    ) -> None:
        """基础分页 + 计数。"""
        result, total = await job_repo.list_by_filter_with_count(
            filters={"user_id": 1},
            page=1,
            page_size=5,
        )

        assert total == 10
        assert len(result) == 5

    async def test_list_by_filter_with_count_filter_status(
        self,
        job_repo: JobRepository,
        seed_jobs: list[Job],
    ) -> None:
        """按状态过滤。"""
        result, total = await job_repo.list_by_filter_with_count(
            filters={"user_id": 1, "status": "active"},
            page=1,
            page_size=10,
        )

        # 偶数是 active，共 5 个
        assert total == 5
        assert len(result) == 5
        for job in result:
            assert job.status == "active"

    async def test_list_by_filter_with_count_pagination(
        self,
        job_repo: JobRepository,
        seed_jobs: list[Job],
    ) -> None:
        """分页边界测试。"""
        # 第一页
        result1, total1 = await job_repo.list_by_filter_with_count(
            filters={"user_id": 1},
            page=1,
            page_size=3,
        )
        assert total1 == 10
        assert len(result1) == 3

        # 第二页
        result2, total2 = await job_repo.list_by_filter_with_count(
            filters={"user_id": 1},
            page=2,
            page_size=3,
        )
        assert total2 == 10
        assert len(result2) == 3

        # 最后一页（不足一页）
        result3, total3 = await job_repo.list_by_filter_with_count(
            filters={"user_id": 1},
            page=4,
            page_size=3,
        )
        assert total3 == 10
        assert len(result3) == 1

        # 超出范围
        result4, total4 = await job_repo.list_by_filter_with_count(
            filters={"user_id": 1},
            page=10,
            page_size=3,
        )
        assert total4 == 10
        assert len(result4) == 0

    async def test_list_by_filter_with_count_ordering(
        self,
        job_repo: JobRepository,
        seed_jobs: list[Job],
    ) -> None:
        """排序测试（默认按 created_at 倒序）。"""
        result, _ = await job_repo.list_by_filter_with_count(
            filters={"user_id": 1},
            page=1,
            page_size=10,
            order_by="id",
        )

        # 验证按 id 倒序
        ids = [job.id for job in result]
        assert ids == sorted(ids, reverse=True)

    async def test_list_by_filter_with_count_empty(
        self,
        job_repo: JobRepository,
        seed_user: int,
    ) -> None:
        """空结果测试。"""
        result, total = await job_repo.list_by_filter_with_count(
            filters={"user_id": 999},  # 不存在的用户
            page=1,
            page_size=10,
        )

        assert total == 0
        assert len(result) == 0

    async def test_count_by_filter(
        self,
        job_repo: JobRepository,
        seed_jobs: list[Job],
    ) -> None:
        """条件计数测试。"""
        total_all = await job_repo.count_by_filter(filters={"user_id": 1})
        assert total_all == 10

        total_active = await job_repo.count_by_filter(
            filters={"user_id": 1, "status": "active"}
        )
        assert total_active == 5

        total_applied = await job_repo.count_by_filter(
            filters={"user_id": 1, "status": "applied"}
        )
        assert total_applied == 5

        total_none = await job_repo.count_by_filter(filters={"user_id": 999})
        assert total_none == 0
