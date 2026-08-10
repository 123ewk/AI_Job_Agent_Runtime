"""职位管理路由。

提供职位列表查询、详情、CRUD 以及 HR 信息管理。
所有接口按用户隔离，支持多平台数据聚合。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, JobServiceDep
from app.core.logging import get_logger
from app.schema.common import PaginatedResponse, PaginationParams, StatusResponse
from app.schema.job import HRCreate, HRResponse, JobCreate, JobFilterParams, JobResponse, JobUpdate

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = get_logger("app.api.jobs")


@router.get("", response_model=PaginatedResponse[JobResponse])
async def list_jobs(
    user_id: CurrentUserDep,
    service: JobServiceDep,
    filters: Annotated[JobFilterParams, Depends()],
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[JobResponse]:
    """获取用户职位列表。

    支持按状态、匹配度、平台筛选，支持关键词搜索。
    """
    return await service.list(
        user_id,
        filters,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    user_id: CurrentUserDep,
    service: JobServiceDep,
    job_id: int,
) -> JobResponse:
    """获取职位详情。"""
    return await service.get_by_id(user_id, job_id)


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    user_id: CurrentUserDep,
    service: JobServiceDep,
    data: JobCreate,
) -> JobResponse:
    """创建新职位。

    同平台同 external_id 自动去重。
    """
    return await service.create(user_id, data)


@router.put("/{job_id}", response_model=JobResponse)
async def update_job(
    user_id: CurrentUserDep,
    service: JobServiceDep,
    job_id: int,
    data: JobUpdate,
) -> JobResponse:
    """更新职位信息。"""
    return await service.update(user_id, job_id, data)


@router.delete("/{job_id}", response_model=StatusResponse)
async def delete_job(
    user_id: CurrentUserDep,
    service: JobServiceDep,
    job_id: int,
) -> StatusResponse:
    """删除职位。"""
    await service.delete(user_id, job_id)
    return StatusResponse(status="ok", message="职位已删除")


@router.get("/hr/list", response_model=PaginatedResponse[HRResponse])
async def list_hr(
    user_id: CurrentUserDep,
    service: JobServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[HRResponse]:
    """获取 HR 列表。"""
    return await service.list_hr(
        user_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("/hr", response_model=HRResponse, status_code=201)
async def create_hr(
    user_id: CurrentUserDep,
    service: JobServiceDep,
    data: HRCreate,
) -> HRResponse:
    """创建或更新 HR 信息。"""
    return await service.create_hr(user_id, data)
