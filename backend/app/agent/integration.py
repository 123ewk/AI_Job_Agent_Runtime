"""垂直技能 → backend Service 的瘦适配器（激活技能的持久化接线点）。

背景：boss.extract_jobs / boss.chat 两个垂直技能按 docstring「未来接线点」预留了
job_service / settings_service / store 注入位，但装配期（main.py）从未注入，导致技能
「读取+筛选/发送都做了、落库静默没做」。本模块补齐这层：把 backend 的
JobService / ConversationService / SettingsService 包成技能期望的 duck-typing 形状。

设计要点：
- **每方法新开短 session**：图执行分钟级，长事务会占死连接池；DB 每操作一个短会话
  提交即关，副作用自包含、支持节点重试（对齐 memory 决策）。
- **幂等由 backend Service 负责**：JobService.create / ConversationService.create /
  ConversationService.add_message 均已按 platform+external_id / external_msg_id 去重，
  适配器不再重复去重，薄薄一层只做「dict -> Schema」映射。
- 本层位于 agent 编排层，import app.service.* 是合法的编排层 -> 服务层依赖，无环。

注意：技能已内联落库，故这里**不**返回 needs_persist，也不会触发 graph sync 节点
（否则二次落库）。sync 节点保留给未来无自持久化的通用工具。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.schema.conversation import ConversationCreate, MessageCreate
from app.schema.job import JobCreate, JobUpdate


class SessionFactory(Protocol):
    """异步会话工厂（async_sessionmaker，async with 上下文管理）。"""

    def __call__(self) -> AsyncSession: ...


class JobStoreAdapter:
    """实现技能侧 JobServiceLike.create(user_id, payload_dict) -> JobResponse。

    payload 是 BossExtractService._to_create_payload 产出的 dict（含 score_detail）；
    拆成 JobCreate（去 score_detail）落库，再按需 JobUpdate(score_detail) 补评分明细。
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._factory = session_factory

    async def create(self, user_id: int, payload: dict[str, Any]) -> object:
        """JobService.create 幂等去重 + 补 score_detail，返回 JobResponse。"""
        score_detail = payload.pop("score_detail", None)
        job = JobCreate(**payload)
        async with self._factory() as session:
            from app.service.job import JobService

            job_resp, _is_new = await JobService(session).create(user_id, job)
            job_id = int(job_resp.id)
            if score_detail:
                await JobService(session).update(
                    user_id,
                    job_id,
                    JobUpdate(score_detail=score_detail),
                )
            return job_resp


class ChatStoreAdapter:
    """实现技能侧 ChatStoreLike（upsert_conversation + append_messages）。

    - upsert_conversation：external_id+hr_name -> ConversationCreate(platform="boss")，
      ConversationService.create 幂等。
    - append_messages：每消息 -> MessageCreate(source="history")，
      ConversationService.add_message 按 external_msg_id 幂等。
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._factory = session_factory

    async def _session_services(self) -> AsyncIterator[Any]:
        """open 一个短 session，产出 (session, ConversationService)。"""
        from app.service.conversation import ConversationService

        async with self._factory() as session:
            yield session, ConversationService(session)

    async def upsert_conversation(self, user_id: int, conv: dict[str, Any]) -> object:
        """幂等 upsert 会话，返回 ConversationResponse（含 id）。"""
        create = ConversationCreate(
            platform="boss",
            external_id=conv["external_id"],
            hr_name=conv.get("hr_name"),
        )
        async with self._factory() as session:
            from app.service.conversation import ConversationService

            return await ConversationService(session).create(user_id, create)

    async def append_messages(
        self,
        user_id: int,
        conversation_id: int,
        msgs: list[dict[str, Any]],
    ) -> list[Any]:
        """逐条幂等落库消息，返回 MessageResponse 列表。"""
        saved: list[Any] = []
        for msg in msgs:
            create = MessageCreate(
                conversation_id=conversation_id,
                role=msg.get("role") or "hr",
                content=msg.get("content") or "",
                external_msg_id=msg.get("external_msg_id"),
                sent_at=msg.get("sent_at"),
                source="history",
            )
            async with self._factory() as session:
                from app.service.conversation import ConversationService

                saved.append(await ConversationService(session).add_message(user_id, conversation_id, create))
        return saved


class SettingsStoreAdapter:
    """实现技能侧 settings_service.get_job_rule(user_id)。

    返回 backend SettingsService.get_job_rule 的 JobRuleConfigResponse；技能侧
    BossExtractService._coerce_rules 已容忍该对象（getattr 取值）。
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._factory = session_factory

    async def get_job_rule(self, user_id: int) -> object:
        async with self._factory() as session:
            from app.service.setting import SettingsService

            return await SettingsService(session).get_job_rule(user_id)
