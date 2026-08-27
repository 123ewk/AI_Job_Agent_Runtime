"""任务管理路由。

提供任务列表、详情、创建、取消、审批等功能。
任务是 Agent 执行的最小单元，支持优先级队列与状态流转。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, SettingsServiceDep, TaskServiceDep
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.schema.common import PaginatedResponse, StatusResponse
from app.schema.task import (
    ApprovalResponse,
    TaskApproveRequest,
    TaskCreate,
    TaskFilterParams,
    TaskResponse,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = get_logger("app.api.tasks")


@router.get("", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    user_id: CurrentUserDep,
    service: TaskServiceDep,
    filters: Annotated[TaskFilterParams, Depends()],
) -> PaginatedResponse[TaskResponse]:
    """获取用户任务列表。

    支持按状态、类型、会话筛选，支持分页。
    TaskFilterParams 已继承 PaginationParams，page/page_size 直接取 filters 上的。
    """
    tasks, total = await service.list(
        user_id,
        filters,
        page=filters.page,
        page_size=filters.page_size,
    )
    return PaginatedResponse(
        items=tasks,
        total=total,
        page=filters.page,
        page_size=filters.page_size,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    user_id: CurrentUserDep,
    service: TaskServiceDep,
    task_id: int,
) -> TaskResponse:
    """获取任务详情。

    包含当前状态、进度、执行结果、错误信息。
    """
    return await service.get_by_id(user_id, task_id)


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    user_id: CurrentUserDep,
    service: TaskServiceDep,
    data: TaskCreate,
) -> TaskResponse:
    """创建新任务并入队。

    任务类型与优先级映射（与 _get_priority_by_type / doc 04 保持一致）：
    - approval_resume: 人工确认后继续（P0）
    - recovery: 故障恢复（P0）
    - hr_reply: HR 消息回复（P1）
    - sync: 数据同步（P1）
    - user_initiated: 用户主动触发（P2）
    - proactive_chat: 主动打招呼（P2）
    - proactive_job: 主动求职（P3）
    - background_scan: 后台扫描（P3）

    优先级自动分配，任务创建后进入队列等待执行。
    """
    return await service.create(user_id, data)


@router.post("/{task_id}/cancel", response_model=StatusResponse)
async def cancel_task(
    user_id: CurrentUserDep,
    service: TaskServiceDep,
    task_id: int,
) -> StatusResponse:
    """取消任务。

    支持取消 pending 或 running 状态的任务。
    running 任务会在下一个检查点中断。
    """
    await service.cancel(user_id, task_id)
    return StatusResponse(status="ok", message="任务已取消")


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    user_id: CurrentUserDep,
    service: TaskServiceDep,
    task_id: int,
) -> TaskResponse:
    """重试失败任务。

    受 max_retries 约束（默认 2 次），
    重用原有 thread_id 延续上下文。
    """
    return await service.retry(user_id, task_id)


@router.get("/{task_id}/approvals/pending", response_model=ApprovalResponse | None)
async def get_pending_approval(
    user_id: CurrentUserDep,
    service: TaskServiceDep,
    task_id: int,
) -> ApprovalResponse | None:
    """获取任务待处理的审批。

    任务执行到需要人工确认的节点时，会产生 pending 状态的 approval。
    先校验任务归属（防止越权读取他人审批信息）。
    """
    # 先校验任务归属：不存在或不属于当前用户均抛 404，不暴露 task_id 是否存在
    await service.get_by_id(user_id, task_id)

    from app.repository.approval import ApprovalRepository

    approval_repo = ApprovalRepository(service.db)
    approval = await approval_repo.get_latest_pending_by_task(task_id)
    if approval is None:
        return None
    return ApprovalResponse.model_validate(approval, from_attributes=True)


@router.post("/{task_id}/approvals/approve", response_model=StatusResponse)
async def approve_task(
    user_id: CurrentUserDep,
    service: TaskServiceDep,
    task_id: int,
    data: TaskApproveRequest,
) -> StatusResponse:
    """对任务待处理审批做决策（批准或拒绝）。

    ``approved=True`` → 批准，任务从 waiting_approval 恢复执行；
    ``approved=False`` → 拒绝，任务进入 canceled 终态（等价于调用 /deny）。
    决策结果会写入 approval 记录，作为后续 LLM 微调数据。

    注：接口路径名 ``/approve`` 为历史遗留，实际支持双向决策，保持
    与前端契约（``TaskApproveRequest.approved`` 字段）一致。
    """
    # 先校验任务归属：不存在或不属于当前用户均抛 404，不暴露 task_id 是否存在
    await service.get_by_id(user_id, task_id)

    from app.repository.approval import ApprovalRepository
    from app.service.approval import ApprovalService

    approval_repo = ApprovalRepository(service.db)
    approval = await approval_repo.get_latest_pending_by_task(task_id)
    if approval is None:
        raise NotFoundError("任务没有待处理的审批")

    # 使用请求体里的 approved 字段决定走批准或拒绝路径
    approval_service = ApprovalService(service.db)
    if data.approved:
        await approval_service.approve(data.approval_id, user_id, data.user_note)
        return StatusResponse(status="ok", message="已批准")
    await approval_service.deny(data.approval_id, user_id, data.user_note)
    return StatusResponse(status="ok", message="已拒绝")


@router.post("/{task_id}/approvals/deny", response_model=StatusResponse)
async def deny_task(
    user_id: CurrentUserDep,
    service: TaskServiceDep,
    task_id: int,
) -> StatusResponse:
    """拒绝任务继续执行。

    拒绝后任务进入 canceled 终态，不会再重试。
    决策结果会写入 approval 记录。
    """
    # 先校验任务归属：不存在或不属于当前用户均抛 404，不暴露 task_id 是否存在
    await service.get_by_id(user_id, task_id)

    from app.repository.approval import ApprovalRepository
    from app.service.approval import ApprovalService

    approval_repo = ApprovalRepository(service.db)
    approval = await approval_repo.get_latest_pending_by_task(task_id)
    if approval is None:
        raise NotFoundError("任务没有待处理的审批")

    approval_service = ApprovalService(service.db)
    # deny 签名 (approval_id, user_id, reason=None)，传入当前用户
    await approval_service.deny(approval.id, user_id)
    return StatusResponse(status="ok", message="已拒绝")


@router.get("/queue/stats")
async def get_queue_stats(
    user_id: CurrentUserDep,
    service: TaskServiceDep,
    settings_service: SettingsServiceDep,
) -> dict:
    """获取任务队列统计。

    返回各状态任务数，用于 Dashboard 展示。
    max_concurrent 从 SettingsService 读取 agent.concurrency_limit，
    而非硬编码，确保与 Agent 执行器一致。
    """
    pending_count = await service.get_pending_tasks_count(user_id)
    agent_config = await settings_service.get_agent_config(user_id)
    return {
        "pending": pending_count,
        "max_concurrent": agent_config.concurrency_limit,
    }
