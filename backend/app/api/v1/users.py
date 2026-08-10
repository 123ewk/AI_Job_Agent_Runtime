"""用户管理路由。

V1 为单用户模式，此处提供用户信息查询、配置更新等基础接口。
多用户版本（V2+）将补充注册、JWT 登录、权限管理等功能。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, DBSessionDep, TaskServiceDep
from app.core.logging import get_logger
from app.schema.common import PaginatedResponse
from app.schema.task import TaskFilterParams, TaskResponse

router = APIRouter(prefix="/users", tags=["users"])
logger = get_logger("app.api.users")


@router.get("/me")
async def get_current_user(
    user_id: CurrentUserDep,
) -> dict:
    """获取当前用户信息。

    V1 单用户模式，返回固定用户基本信息。
    """
    return {
        "id": user_id,
        "email": "user@example.com",
        "is_active": True,
    }


@router.get("/me/tasks", response_model=PaginatedResponse[TaskResponse])
async def get_my_tasks(
    user_id: CurrentUserDep,
    task_service: TaskServiceDep,
    filters: Annotated[TaskFilterParams, Depends()],
) -> PaginatedResponse[TaskResponse]:
    """获取当前用户的任务列表。"""
    tasks, total = await task_service.list(
        user_id, filters, page=filters.page, page_size=filters.page_size
    )
    return PaginatedResponse(
        items=tasks,
        total=total,
        page=filters.page,
        page_size=filters.page_size,
    )


@router.get("/me/stats")
async def get_my_stats(
    user_id: CurrentUserDep,
    db: DBSessionDep,
    task_service: TaskServiceDep,
) -> dict:
    """获取用户统计信息（任务数、活跃会话数等）。"""
    from app.repository import ConversationRepository, JobRepository

    job_repo = JobRepository(db)
    conv_repo = ConversationRepository(db)

    pending_count = await task_service.get_pending_tasks_count(user_id)
    active_convs = await conv_repo.count_active(user_id)
    total_jobs = await job_repo.count_by_user(user_id)

    return {
        "pending_tasks": pending_count,
        "active_conversations": active_convs,
        "total_jobs": total_jobs,
    }
