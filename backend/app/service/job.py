"""职位业务服务。

负责 Job 与 HR 的生命周期管理、匹配度计算、状态流转。
Job 是从 Boss 拉取的职位信息，关联 Conversation 与 HR。

跨域协作：
- 与 Sync 系统协作：拉取 Boss 职位列表并去重落库
- 与 Memory 系统协作：提取职位关键信息为记忆
- 与 Agent 系统协作：提供职位上下文给 Planner
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repository.hr import HRRepository
from app.repository.job import JobRepository
from app.schema.common import PaginatedResponse
from app.schema.job import HRCreate, HRResponse, JobCreate, JobFilterParams, JobResponse, JobUpdate
from app.service.base import BaseService, transactional


class JobService(BaseService):
    """职位业务服务。

    职责：
    - Job CRUD 与状态管理
    - HR 信息管理
    - 职位匹配度计算与排序
    - 职位筛选与分页
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)
        self.job_repo = JobRepository(db)
        self.hr_repo = HRRepository(db)

    @transactional
    async def create(self, user_id: int, data: JobCreate) -> JobResponse:
        """创建新职位。

        同平台同 external_id 做去重，已存在则直接返回。
        """
        existing = await self.job_repo.get_by_platform_external(data.platform, data.external_id)
        if existing:
            self.logger.info(
                "job_already_exists",
                extra={"user_id": user_id, "platform": data.platform, "external_id": data.external_id},
            )
            return JobResponse.model_validate(existing, from_attributes=True)

        job_data = data.model_dump(exclude_unset=True)
        job_data["user_id"] = user_id
        job = await self.job_repo.create(job_data)

        self.logger.info(
            "job_created",
            extra={"user_id": user_id, "job_id": job.id, "platform": job.platform},
        )

        return JobResponse.model_validate(job, from_attributes=True)

    async def get_by_id(self, user_id: int, job_id: int) -> JobResponse:
        """获取职位详情。"""
        job = await self.job_repo.get_by_unique(id=job_id, user_id=user_id)
        if not job:
            raise NotFoundError(f"职位不存在: {job_id}")
        return JobResponse.model_validate(job, from_attributes=True)

    async def list(
        self, user_id: int, filters: JobFilterParams, page: int = 1, page_size: int = 20
    ) -> PaginatedResponse[JobResponse]:
        """获取用户职位列表，支持筛选与分页。"""
        filter_dict: dict[str, Any] = {"user_id": user_id}

        if filters.status is not None:
            filter_dict["status"] = filters.status.value if hasattr(filters.status, "value") else filters.status
        if filters.platform is not None:
            filter_dict["platform"] = filters.platform

        jobs, total = await self.job_repo.list_by_filter_with_count(
            filters=filter_dict,
            page=page,
            page_size=page_size,
        )

        items = [JobResponse.model_validate(j, from_attributes=True) for j in jobs]
        return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)

    @transactional
    async def update(self, user_id: int, job_id: int, data: JobUpdate) -> JobResponse:
        """更新职位信息。"""
        job = await self.job_repo.get_by_unique(id=job_id, user_id=user_id)
        if not job:
            raise NotFoundError(f"职位不存在: {job_id}")

        update_data = data.model_dump(exclude_unset=True)
        job = await self.job_repo.update(job_id, update_data)

        self.logger.info("job_updated", extra={"user_id": user_id, "job_id": job_id})
        return JobResponse.model_validate(job, from_attributes=True)

    @transactional
    async def delete(self, user_id: int, job_id: int) -> None:
        """删除职位（软删除或硬删除，根据架构选择）。

        当前实现为硬删除，关联 conversation 不受影响（外键置空）。
        """
        job = await self.job_repo.get_by_unique(id=job_id, user_id=user_id)
        if not job:
            raise NotFoundError(f"职位不存在: {job_id}")

        await self.job_repo.delete(job_id)
        self.logger.info("job_deleted", extra={"user_id": user_id, "job_id": job_id})

    @transactional
    async def create_hr(self, user_id: int, data: HRCreate) -> HRResponse:
        """创建或更新 HR 信息。"""
        existing = await self.hr_repo.get_by_external_id(data.platform, data.external_id, user_id)
        if existing:
            self.logger.info(
                "hr_already_exists",
                extra={"user_id": user_id, "platform": data.platform, "external_id": data.external_id},
            )
            return HRResponse.model_validate(existing, from_attributes=True)

        hr_data = data.model_dump(exclude_unset=True)
        hr_data["user_id"] = user_id
        hr = await self.hr_repo.create(hr_data)

        self.logger.info("hr_created", extra={"user_id": user_id, "hr_id": hr.id})
        return HRResponse.model_validate(hr, from_attributes=True)

    async def list_hr(self, user_id: int, page: int = 1, page_size: int = 50) -> PaginatedResponse[HRResponse]:
        """获取用户 HR 列表。"""
        hrs, total = await self.hr_repo.list_by_filter_with_count(
            {"user_id": user_id},
            page=page,
            page_size=page_size,
        )
        items = [HRResponse.model_validate(h, from_attributes=True) for h in hrs]
        return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)
