"""会话管理路由。

提供会话列表、消息历史、手动发送消息等功能。
会话是 Agent 与 HR 沟通的线程，每条消息全量落库。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ConversationServiceDep, CurrentUserDep
from app.core.logging import get_logger
from app.schema.common import PaginatedResponse, PaginationParams, StatusResponse
from app.schema.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    MessageResponse,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = get_logger("app.api.conversations")


@router.get("", response_model=PaginatedResponse[ConversationResponse])
async def list_conversations(
    user_id: CurrentUserDep,
    service: ConversationServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[ConversationResponse]:
    """获取用户会话列表。

    按最后更新时间倒序排列，展示 HR 姓名、职位标题、
    最后一条消息预览等信息。
    """
    convs, total = await service.list_by_user(
        user_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return PaginatedResponse(
        items=convs,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    user_id: CurrentUserDep,
    service: ConversationServiceDep,
    conversation_id: int,
) -> ConversationResponse:
    """获取会话详情。"""
    return await service.get_by_id(user_id, conversation_id)


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    user_id: CurrentUserDep,
    service: ConversationServiceDep,
    data: ConversationCreate,
) -> ConversationResponse:
    """创建新会话。

    创建前检查并发数限制（max_concurrent_chats），
    超过限制时返回错误。同平台同 external_id 自动去重。
    """
    return await service.create(user_id, data)


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    user_id: CurrentUserDep,
    service: ConversationServiceDep,
    conversation_id: int,
    data: ConversationUpdate,
) -> ConversationResponse:
    """更新会话元数据（HR 姓名、职位标题、状态等）。"""
    return await service.update(user_id, conversation_id, data)


@router.post("/{conversation_id}/close", response_model=StatusResponse)
async def close_conversation(
    user_id: CurrentUserDep,
    service: ConversationServiceDep,
    conversation_id: int,
) -> StatusResponse:
    """关闭会话。

    关闭后不再生成回复任务，但仍可查询历史消息。
    """
    await service.close(user_id, conversation_id)
    return StatusResponse(status="ok", message="会话已关闭")


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    user_id: CurrentUserDep,
    service: ConversationServiceDep,
    conversation_id: int,
    limit: int = Query(100, ge=1, le=500, description="消息数量上限"),
) -> list[MessageResponse]:
    """获取会话消息历史。

    按发送时间正序排列。limit 上限 500，防止全表扫描。
    """
    return await service.list_messages(user_id, conversation_id, limit=limit)


@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=201)
async def add_message(
    user_id: CurrentUserDep,
    service: ConversationServiceDep,
    conversation_id: int,
    data: MessageCreate,
) -> MessageResponse:
    """添加消息到会话。

    - 用户手动发送消息：source=manual, role=user
    - Agent 发送消息：source=agent, role=agent
    - HR 回复消息：source=history, role=hr
    - system: 系统消息

    如果是 HR 消息（role=hr），会自动触发生成回复任务。
    """
    data.conversation_id = conversation_id
    return await service.add_message(user_id, conversation_id, data)


@router.post("/{conversation_id}/sync", response_model=StatusResponse)
async def sync_boss_messages(
    user_id: CurrentUserDep,
    service: ConversationServiceDep,
    conversation_id: int,
) -> StatusResponse:
    """从 Boss 页面同步新消息。

    触发 Chrome Skill 拉取页面消息并去重落库。
    当前功能未实现（依赖同步方案 §8.2 定案），调用即返回 501。
    """
    count = await service.sync_boss_messages(user_id, conversation_id)
    return StatusResponse(status="ok", message=f"同步完成，新增 {count} 条消息")


@router.get("/unreplied/check")
async def check_unreplied_messages(
    user_id: CurrentUserDep,
    service: ConversationServiceDep,
) -> dict:
    """检查未回复的 HR 消息。

    返回所有活跃会话中未回复的 HR 消息列表。
    """
    messages = await service.get_unreplied_messages(user_id)
    return {"count": len(messages), "messages": messages}
