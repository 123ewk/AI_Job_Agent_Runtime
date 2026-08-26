"""会话业务服务。

负责 Conversation 与 Message 的生命周期管理、同步、去重。
Conversation 是 Agent 与 HR 的聊天线程，每条消息全量入库。

跨域协作：
- 与 Sync 系统协作：拉取 Boss 新消息并去重落库
- 与 Task 系统协作：新消息触发生成回复任务
- 与 Memory 系统协作：重要消息提取为长期记忆
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, NotImplementedError
from app.models.conversation import Conversation
from app.models.message import Message
from app.repository.conversation import ConversationRepository
from app.repository.message import MessageRepository
from app.schema.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    MessageResponse,
)
from app.service.base import BaseService, transactional
from app.service.task import TaskService

# 默认并发数限制（实际应从 SettingsService 读取）
DEFAULT_MAX_CONCURRENT_CHATS = 3

# role -> 缺省 source 映射。
# model_dump(exclude_unset=True) 会丢弃 schema 默认值（source="manual"），
# 落库时若未显式传 source 则按 role 推断补回，避免 messages.source NOT NULL 违约。
_ROLE_DEFAULT_SOURCE = {
    "user": "manual",  # 用户手动发送
    "agent": "agent",  # Agent 发送
    "hr": "history",  # 页面历史记录
    "system": "manual",  # 系统消息
}


class ConversationService(BaseService):
    """会话业务服务。

    职责：
    - Conversation CRUD 与状态管理
    - Message 入库与去重（靠 external_msg_id）
    - 主动开聊前的并发数校验（max_concurrent_chats）
    - 新消息检测与回复任务触发
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)

    @transactional
    async def create(self, user_id: int, data: ConversationCreate) -> ConversationResponse:
        """创建新会话。

        创建前校验：active conversations 数量是否超过 max_concurrent_chats。
        超限时不创建，返回错误（或入队等待）。
        """
        # 1. 校验并发数限制
        active_count = await self.count_active(user_id)
        if active_count >= DEFAULT_MAX_CONCURRENT_CHATS:
            error_msg = (
                f"活跃会话数已达上限 {active_count}/{DEFAULT_MAX_CONCURRENT_CHATS}，"
                "请先关闭部分会话或提高并发限制"
            )
            self.logger.warning(
                "conversation_limit_exceeded",
                extra={"user_id": user_id, "active_count": active_count, "limit": DEFAULT_MAX_CONCURRENT_CHATS},
            )
            raise ConflictError(error_msg)

        # 2. 检查同平台同外部 ID 是否已存在
        existing = await self.conversation_repo.get_by_platform_external(data.platform, data.external_id)
        if existing:
            self.logger.info(
                "conversation_already_exists",
                extra={"user_id": user_id, "platform": data.platform, "external_id": data.external_id},
            )
            return ConversationResponse.model_validate(existing, from_attributes=True)

        # 3. 创建会话
        conv_data = data.model_dump(exclude_unset=True)
        conv_data["user_id"] = user_id
        conv_data["status"] = "active"
        conv = await self.conversation_repo.create(conv_data)

        self.logger.info(
            "conversation_created",
            extra={"user_id": user_id, "conversation_id": conv.id, "platform": conv.platform},
        )

        return ConversationResponse.model_validate(conv, from_attributes=True)

    async def get_by_id(self, user_id: int, conversation_id: int) -> ConversationResponse:
        """获取会话详情。"""
        conv = await self.conversation_repo.get_by_unique(id=conversation_id, user_id=user_id)
        if not conv:
            raise NotFoundError(f"会话不存在: {conversation_id}")
        return ConversationResponse.model_validate(conv, from_attributes=True)

    async def list_by_user(
        self, user_id: int, *, page: int = 1, page_size: int = 50
    ) -> tuple[list[ConversationResponse], int]:
        """列出用户的所有会话，按更新时间倒序，返回 (items, total_count)。

        用 list_by_filter_with_count 一次拿到总数，避免 total=len(items) 假计数。
        """
        convs, total = await self.conversation_repo.list_by_filter_with_count(
            {"user_id": user_id},
            order_by="updated_at",
            page=page,
            page_size=page_size,
        )
        return [ConversationResponse.model_validate(c, from_attributes=True) for c in convs], total

    @transactional
    async def update(
        self,
        user_id: int,
        conversation_id: int,
        data: ConversationUpdate,
    ) -> ConversationResponse:
        """更新会话元数据（标签、备注等）。"""
        conv = await self.conversation_repo.get_by_unique(id=conversation_id, user_id=user_id)
        if not conv:
            raise NotFoundError(f"会话不存在: {conversation_id}")

        update_data = data.model_dump(exclude_unset=True)
        await self.conversation_repo.update(conversation_id, update_data)
        conv = await self.conversation_repo.get(conversation_id)

        self.logger.info(
            "conversation_updated",
            extra={"user_id": user_id, "conversation_id": conversation_id, "fields": list(update_data.keys())},
        )

        return ConversationResponse.model_validate(conv, from_attributes=True)

    @transactional
    async def close(self, user_id: int, conversation_id: int) -> None:
        """关闭会话（软删除，保留历史记录）。

        关闭后不再生成回复任务，但仍可查询历史。
        """
        conv = await self.conversation_repo.get_by_unique(id=conversation_id, user_id=user_id)
        if not conv:
            raise NotFoundError(f"会话不存在: {conversation_id}")

        await self.conversation_repo.update(conversation_id, {"status": "closed"})

        self.logger.info(
            "conversation_closed",
            extra={"user_id": user_id, "conversation_id": conversation_id},
        )

    @transactional
    async def add_message(self, user_id: int, conversation_id: int, data: MessageCreate) -> MessageResponse:
        """添加消息。

        去重逻辑：external_msg_id 存在则跳过（防止重复落库）。
        source：agent / user / hr / system。
        如果是 HR 消息，触发生成回复任务。
        """
        # 1. 校验会话归属
        conv = await self.conversation_repo.get_by_unique(id=conversation_id, user_id=user_id)
        if not conv:
            raise NotFoundError(f"会话不存在: {conversation_id}")

        # 2. 去重检查
        if data.external_msg_id:
            existing_msg = await self.message_repo.get_by_external_id(data.external_msg_id)
            if existing_msg:
                self.logger.debug(
                    "message_duplicate_skipped",
                    extra={"user_id": user_id, "external_msg_id": data.external_msg_id},
                )
                return MessageResponse.model_validate(existing_msg, from_attributes=True)

        # 3. 插入消息
        msg_data = data.model_dump(exclude_unset=True)
        msg_data["user_id"] = user_id
        msg_data["conversation_id"] = conversation_id

        # source 缺省时按 role 推断补回（exclude_unset 丢弃了 schema 默认值）
        if "source" not in msg_data:
            msg_data["source"] = _ROLE_DEFAULT_SOURCE.get(data.role, "manual")

        # sent_at 为空时使用当前时间
        if msg_data.get("sent_at") is None:
            msg_data["sent_at"] = datetime.now(timezone.utc)

        msg = await self.message_repo.create(msg_data)

        self.logger.info(
            "message_added",
            extra={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_id": msg.id,
                "role": msg.role,
                "source": msg.source,
            },
        )

        # 4. 如果是 HR 消息，触发生成回复任务
        if msg.role == "hr":
            await self._enqueue_reply_task(user_id, conversation_id, msg.id)

        return MessageResponse.model_validate(msg, from_attributes=True)

    async def list_messages(
        self,
        user_id: int,
        conversation_id: int,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[MessageResponse]:
        """列出会话的消息历史，按发送时间正序。"""
        # 先校验会话归属
        conv = await self.conversation_repo.get_by_unique(id=conversation_id, user_id=user_id)
        if not conv:
            raise NotFoundError(f"会话不存在: {conversation_id}")

        messages = await self.message_repo.list_by_conversation(conversation_id, limit=limit)
        return [MessageResponse.model_validate(m, from_attributes=True) for m in messages]

    async def get_unreplied_messages(self, user_id: int) -> list[dict[str, Any]]:
        """获取所有未回复的 HR 消息。

        供 monitor_tick 检测是否需要生成回复任务。
        判断逻辑：HR 发送的消息晚于同会话中最后一条非 HR 消息。
        """
        # TODO: 优化查询性能，当前逻辑为概念验证
        active_convs = await self.conversation_repo.list_active(user_id)
        unreplied: list[dict[str, Any]] = []

        for conv in active_convs:
            messages = await self.message_repo.list_by_conversation(conv.id, limit=50)
            if not messages:
                continue

            # 找到最后一条 HR 消息和最后一条非 HR 消息
            last_hr_msg: Message | None = None
            last_non_hr_msg: Message | None = None

            for msg in reversed(messages):
                if msg.role == "hr" and last_hr_msg is None:
                    last_hr_msg = msg
                elif msg.role != "hr" and last_non_hr_msg is None:
                    last_non_hr_msg = msg
                if last_hr_msg and last_non_hr_msg:
                    break

            # 如果存在 HR 消息且没有非 HR 消息回复它
            if last_hr_msg is not None:
                if last_non_hr_msg is None or (
                    last_hr_msg.sent_at and last_non_hr_msg.sent_at and last_hr_msg.sent_at > last_non_hr_msg.sent_at
                ):
                    unreplied.append(
                        {
                            "conversation_id": conv.id,
                            "conversation_uuid": str(conv.uuid),
                            "thread_id": str(conv.thread_id),
                            "message_id": last_hr_msg.id,
                            "message_content": last_hr_msg.content,
                            "hr_name": conv.hr_name,
                            "job_title": conv.job_title,
                        }
                    )

        self.logger.debug(
            "unreplied_messages_check",
            extra={"user_id": user_id, "unreplied_count": len(unreplied)},
        )

        return unreplied

    async def sync_boss_messages(self, user_id: int, conversation_id: int) -> int:
        """从 Boss 页面同步新消息并落库。

        由 Sync 系统调用，返回新增消息数。
        去重：依赖 external_msg_id 唯一约束。

        Raises:
            NotImplementedError: 真同步依赖「同步方案 §8.2」定案后接入
                Boss Chat Skill / Chrome 拉取。此前占位返回「新增 0 条」
                属静默假成功，调用方无法感知未实现，故改为明确抛错（501）。
        """
        # 校验会话归属（保留资源语义：不存在的会话仍返回 404）
        conv = await self.conversation_repo.get_by_unique(id=conversation_id, user_id=user_id)
        if not conv:
            raise NotFoundError(f"会话不存在: {conversation_id}")

        self.logger.info(
            "sync_boss_messages_not_implemented",
            extra={"user_id": user_id, "conversation_id": conversation_id},
        )

        msg = "从 Boss 页面同步消息功能尚未实现"
        raise NotImplementedError(msg)

    async def _enqueue_reply_task(self, user_id: int, conversation_id: int, message_id: int) -> None:
        """触发生成回复任务。

        将 hr_reply 类型任务入队 Redis Stream，优先级 P1。
        """
        conv = await self.conversation_repo.get(conversation_id)
        if not conv:
            self.logger.warning(
                "conversation_not_found_for_reply",
                extra={"user_id": user_id, "conversation_id": conversation_id},
            )
            return

        # 调用 TaskService 创建 hr_reply 任务
        task_service = TaskService(self.db)

        # 避免循环 import，延迟导入
        from app.schema.task import TaskCreate, TaskPriority, TaskType

        task_data = TaskCreate(
            type=TaskType.HR_REPLY,
            priority=TaskPriority.P1,
            conversation_id=conversation_id,
            thread_id=str(conv.thread_id),
            triggering_message_id=message_id,
        )

        try:
            await task_service.create(user_id, task_data)
            self.logger.info(
                "reply_task_enqueued",
                extra={"user_id": user_id, "conversation_id": conversation_id, "message_id": message_id},
            )
        except Exception as exc:
            self.logger.exception(
                "enqueue_reply_task_failed",
                extra={"user_id": user_id, "conversation_id": conversation_id, "error": str(exc)},
            )

    async def count_active(self, user_id: int) -> int:
        """统计用户当前活跃会话数。

        用于 max_concurrent_chats 限流检查。
        """
        result = await self.db.execute(
            select(Conversation.id).where(
                and_(
                    Conversation.user_id == user_id,
                    Conversation.status == "active",
                )
            )
        )
        return len(list(result.scalars().all()))
