"""集成：垂直技能 + backend Service 适配器（app/agent/integration.py）真落 DB。

连测试库（test_session_factory 绑定 test_engine）。验证技能 read ⾥即落库的接线点真正生效：
- BossExtractService + JobStoreAdapter + SettingsStoreAdapter：raw 岗位写入 jobs，二次幂等。
- BossChatService + ChatStoreAdapter：raw 会话写入 conversations，二次幂等。
- ChatStoreAdapter.append_messages：消息写入 messages，外部 id 幂等。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.integration import (
    ChatStoreAdapter,
    JobStoreAdapter,
    SettingsStoreAdapter,
)
from app.agent.skills.boss_chat.service import BossChatService
from app.agent.skills.boss_extract_jobs.service import BossExtractService


async def _count(session_factory: async_sessionmaker[AsyncSession], model: Any) -> int:  # noqa: ANN401
    from sqlalchemy import func, select

    async with session_factory() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def test_extract_raw_jobs_persist_and_idempotent(
    test_session_factory: async_sessionmaker[AsyncSession],
    seed_user: int,
) -> None:
    """raw 岗位：筛选通过 -> JobStoreAdapter 写 jobs；二次运行触发 JobService 幂等去重。"""
    from app.models.job import Job

    svc = BossExtractService(
        adapter=None,
        job_service=JobStoreAdapter(test_session_factory),
        settings_service=SettingsStoreAdapter(test_session_factory),
    )
    jobs = [
        {
            "external_id": "JOB-EXT-1",
            "title": "后端工程师",
            "company": "某公司",
            "salary": "20-40K",
            "location": "上海",
            "source_url": "https://www.zhipin.com/job_detail/JOB-EXT-1.html",
        },
        {
            "external_id": "JOB-EXT-2",
            "title": "前端工程师",
            "company": "某公司",
            "salary": "15-25K",
            "location": "北京",
            "source_url": "https://www.zhipin.com/job_detail/JOB-EXT-2.html",
        },
    ]

    r1 = await svc.run(seed_user, source="raw", jobs=jobs, limit=15)
    assert r1.ok
    assert r1.data["ingested"]  # 至少一条入 inged，说明真正落库
    assert await _count(test_session_factory, Job) == 2

    # 幂等：二次运行同岗位不重复落库
    r2 = await svc.run(seed_user, source="raw", jobs=jobs, limit=15)
    assert r2.ok
    assert await _count(test_session_factory, Job) == 2


async def test_chat_list_raw_persists_conversation_idempotent(
    test_session_factory: async_sessionmaker[AsyncSession],
    seed_user: int,
) -> None:
    """raw 会话：ChatStoreAdapter.upsert_conversation 写 conversations；二次幂等。"""
    from app.models.conversation import Conversation

    svc = BossChatService(adapter=None, store=ChatStoreAdapter(test_session_factory))
    convs = [
        {
            "external_id": "BOSS-ENC-1",
            "hr_name": "王 HR",
            "company": "某公司",
            "position": "招聘经理",
            "last_msg": "你好",
            "last_time": "10:00",
        }
    ]

    r1 = await svc.run(seed_user, operation="list", raw_conversations=convs)
    assert r1.ok
    assert r1.data["ingested"]  # 会话真正落库
    assert await _count(test_session_factory, Conversation) == 1

    r2 = await svc.run(seed_user, operation="list", raw_conversations=convs)
    assert r2.ok
    assert await _count(test_session_factory, Conversation) == 1  # 幂等不重复


async def test_chat_append_messages_persists_idempotent(
    test_session_factory: async_sessionmaker[AsyncSession],
    seed_user: int,
) -> None:
    """ChatStoreAdapter.append_messages：消息写 messages，external_msg_id 幂等。"""
    from app.models.message import Message
    from app.schema.conversation import ConversationCreate
    from app.service.conversation import ConversationService

    # 预置一个已存在会话（与 _op_messages 的落库前提一致：消息挂 conversation_id）
    async with test_session_factory() as session:
        conv = await ConversationService(session).create(
            seed_user,
            ConversationCreate(platform="boss", external_id="BOSS-ENC-9", hr_name="李 HR"),
        )
        conv_id = int(conv.id)

    store = ChatStoreAdapter(test_session_factory)
    msgs = [
        {"external_msg_id": "MSG-1", "role": "hr", "content": "在吗", "sent_at": None},
        {"external_msg_id": "MSG-2", "role": "hr", "content": "方便聊下吗", "sent_at": None},
    ]
    saved = await store.append_messages(seed_user, conv_id, msgs)
    assert len(saved) == 2
    assert await _count(test_session_factory, Message) == 2

    # 幂等：同 external_msg_id 二次追加不重复
    await store.append_messages(seed_user, conv_id, msgs)
    assert await _count(test_session_factory, Message) == 2


async def test_settings_store_adapter_reads_job_rule(
    test_session_factory: async_sessionmaker[AsyncSession],
    seed_user: int,
) -> None:
    """SettingsStoreAdapter.get_job_rule：读 settings 表，未配置返回带最小字段的响应。"""
    adapter = SettingsStoreAdapter(test_session_factory)
    cfg = await adapter.get_job_rule(seed_user)
    # JobRuleConfigResponse 必填字段应存在（overtime/outsourcing/offsite 有默认，min/max 可为 None）
    assert getattr(cfg, "min_salary", None) is None
    assert hasattr(cfg, "preferred_locations")
