"""API 层公共依赖。

依赖方向：api -> service -> repository -> database。
此处仅提供跨层的基础设施依赖（DB 会话、配置），不写业务逻辑。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.base import get_session_factory
from app.service import (
    ApprovalService,
    ConversationService,
    MemoryService,
    ResumeService,
    SettingsService,
    TaskService,
)
from app.service.job import JobService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """注入数据库会话。

    每个请求一个独立 AsyncSession，请求结束自动关闭。
    even 在请求处理抛异常时，async with 也会确保 session.close() 执行，
    避免连接泄漏。会话来自惰性工厂，避免 import 时绑定事件循环。
    """
    async with get_session_factory()() as session:
        yield session


def get_app_settings() -> Settings:
    """注入 Settings 单例。"""
    return get_settings()


# 类型别名简化依赖注入
DBSessionDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


# Service 工厂依赖（每个请求新建 Service 实例，共享 DB 会话）
def get_task_service(db: DBSessionDep) -> TaskService:
    return TaskService(db)


def get_approval_service(db: DBSessionDep) -> ApprovalService:
    return ApprovalService(db)


def get_memory_service(db: DBSessionDep) -> MemoryService:
    return MemoryService(db)


def get_conversation_service(db: DBSessionDep) -> ConversationService:
    return ConversationService(db)


def get_settings_service(db: DBSessionDep) -> SettingsService:
    return SettingsService(db)


def get_job_service(db: DBSessionDep) -> JobService:
    return JobService(db)


def get_resume_service(db: DBSessionDep) -> ResumeService:
    return ResumeService(db)


# Service 依赖类型别名
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
ApprovalServiceDep = Annotated[ApprovalService, Depends(get_approval_service)]
MemoryServiceDep = Annotated[MemoryService, Depends(get_memory_service)]
ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
ResumeServiceDep = Annotated[ResumeService, Depends(get_resume_service)]


async def get_current_user_id() -> int:
    """获取当前用户 ID（单用户模式，默认返回 1）。

    V1 设计为单用户系统，此处简化为固定用户。
    多用户版本需接入 JWT 认证，从 token 解析 user_id。
    """
    # TODO: V2+ 接入 JWT 认证
    return 1


# 当前用户依赖
CurrentUserDep = Annotated[int, Depends(get_current_user_id)]
