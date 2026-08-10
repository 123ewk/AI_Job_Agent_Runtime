"""任务域 Schema 定义。"""

from __future__ import annotations

from pydantic import Field

from app.schema.common import BaseSchema, PaginationParams
from app.schema.enums import ApprovalStatus, ApprovalType, TaskPriority, TaskStatus, TaskType


class TaskBase(BaseSchema):
    """任务基础字段。"""

    type: TaskType = Field(..., description="任务类型")
    conversation_id: int | None = Field(None, description="关联会话 ID")
    job_id: int | None = Field(None, description="关联职位 ID")


class TaskCreate(TaskBase):
    """创建任务请求。"""

    priority: TaskPriority | None = Field(None, description="优先级：P0/P1/P2/P3，为空时按任务类型自动分配")
    params: dict | None = Field(None, description="任务参数（JSON）")
    thread_id: str | None = Field(None, description="关联执行线程 ID（LangGraph thread_id）")
    triggering_message_id: int | None = Field(None, description="触发此任务的消息 ID")


class TaskUpdate(BaseSchema):
    """更新任务请求（仅用于手动更新，状态流转由 Service 控制）。"""

    priority: TaskPriority | None = Field(None, description="优先级：P0/P1/P2/P3")


class TaskResponse(TaskBase):
    """任务信息响应。"""

    id: int = Field(..., description="任务 ID")
    user_id: int = Field(..., description="用户 ID")
    status: TaskStatus = Field(..., description="任务状态")
    priority: TaskPriority = Field(..., description="优先级：P0/P1/P2/P3")
    retry_count: int = Field(..., description="已重试次数")
    max_retries: int = Field(..., description="最大重试次数")
    progress: int = Field(0, ge=0, le=100, description="进度百分比")
    error_message: str | None = Field(None, description="错误信息")
    result: dict | None = Field(None, description="任务结果（JSON）")
    started_at: str | None = Field(None, description="开始时间")
    completed_at: str | None = Field(None, description="完成时间")
    created_at: str = Field(..., description="创建时间")


class TaskFilterParams(PaginationParams):
    """任务筛选参数（继承分页参数，list 路由统一走 query params）。"""

    status: TaskStatus | None = Field(None, description="按状态筛选")
    type: TaskType | None = Field(None, description="按类型筛选")
    conversation_id: int | None = Field(None, description="按会话筛选")
    job_id: int | None = Field(None, description="按职位筛选")


class TaskApproveRequest(BaseSchema):
    """人工确认请求（用户批准/拒绝待确认项）。"""

    approval_id: int = Field(..., description="确认项 ID")
    approved: bool = Field(..., description="是否批准")
    user_note: str | None = Field(None, description="用户备注")


class ApprovalResponse(BaseSchema):
    """人工确认项响应。"""

    id: int = Field(..., description="确认项 ID")
    task_id: int = Field(..., description="关联任务 ID")
    user_id: int = Field(..., description="用户 ID")
    type: ApprovalType = Field(..., description="确认类型")
    payload: dict = Field(..., description="确认内容（JSON）")
    status: ApprovalStatus = Field(..., description="确认状态")
    expires_at: str | None = Field(None, description="超时时间")
    decided_at: str | None = Field(None, description="用户决策时间")
    created_at: str = Field(..., description="创建时间")


class TaskEvent(BaseSchema):
    """任务事件（WebSocket 推送）。"""

    task_id: int = Field(..., description="任务 ID")
    event: str = Field(..., description="事件类型：status_update / progress_update / log_append")
    data: dict | None = Field(None, description="事件数据")
    timestamp: str = Field(..., description="事件时间")
