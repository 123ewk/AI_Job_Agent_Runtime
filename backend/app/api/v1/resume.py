"""简历管理路由。

提供简历列表、详情、创建、设为默认、删除接口（对齐 doc 10 §12）。
所有接口按用户隔离（V1 单用户 user_id=1）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, ResumeServiceDep
from app.core.logging import get_logger
from app.schema.common import PaginatedResponse, PaginationParams, StatusResponse
from app.schema.resume import ResumeCreate, ResumeDetailResponse, ResumeResponse

router = APIRouter(prefix="/resumes", tags=["resumes"])
logger = get_logger("app.api.resumes")


@router.get("", response_model=PaginatedResponse[ResumeResponse])
async def list_resumes(
    user_id: CurrentUserDep,
    service: ResumeServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[ResumeResponse]:
    """获取当前用户简历列表（按更新时间倒序）。"""
    return await service.list(
        user_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{resume_id}", response_model=ResumeDetailResponse)
async def get_resume(
    user_id: CurrentUserDep,
    service: ResumeServiceDep,
    resume_id: int,
) -> ResumeDetailResponse:
    """获取简历详情（含解析后原文）。"""
    return await service.get(user_id, resume_id)


@router.post("", response_model=ResumeResponse, status_code=201)
async def create_resume(
    user_id: CurrentUserDep,
    service: ResumeServiceDep,
    data: ResumeCreate,
) -> ResumeResponse:
    """创建简历。

    V1 用 JSON 文本（name + content）而非 doc 10 §12 的 multipart 文件：
    文件存储（MinIO）与文档解析管线尚未接线，如实偏离原设计。
    """
    return await service.create(user_id, data)


@router.post("/{resume_id}/activate", response_model=ResumeResponse)
async def activate_resume(
    user_id: CurrentUserDep,
    service: ResumeServiceDep,
    resume_id: int,
) -> ResumeResponse:
    """将简历设为默认（投递用）。"""
    return await service.set_default(user_id, resume_id)


@router.delete("/{resume_id}", response_model=StatusResponse)
async def delete_resume(
    user_id: CurrentUserDep,
    service: ResumeServiceDep,
    resume_id: int,
) -> StatusResponse:
    """删除简历（硬删除，关联摘要随外键 CASCADE）。"""
    await service.delete(user_id, resume_id)
    return StatusResponse(status="ok", message="简历已删除")
