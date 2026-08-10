"""实证探针：验证 5 个 service create 路径的真实行为。

确认模型层与 schema 层的命名分歧，以及 flush/事务问题。
"""

from __future__ import annotations

import asyncio
import os

# 测试环境配置（必须在 import app 前打补丁）
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/copilot_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["LOG_LEVEL"] = "WARNING"

from unittest.mock import patch  # noqa: E402

from app.core.config import Settings  # noqa: E402

TEST_SETTINGS = Settings(
    database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/copilot_test",
    redis_url="redis://localhost:6379/1",
    log_level="WARNING",
    debug=False,
)

with patch("app.core.config.get_settings", return_value=TEST_SETTINGS):
    import app.models  # noqa: F401, E402  注册 metadata
    from app.db.base import Base, get_engine, get_session_factory  # noqa: E402
    from app.schema.conversation import ConversationCreate  # noqa: E402
    from app.schema.enums import MemoryType, TaskType  # noqa: E402
    from app.schema.job import HRCreate, JobCreate  # noqa: E402
    from app.schema.memory import MemoryCreate  # noqa: E402
    from app.schema.task import TaskCreate, TaskType as TT  # noqa: E402
    from app.service.conversation import ConversationService  # noqa: E402
    from app.service.job import JobService  # noqa: E402
    from app.service.memory import MemoryService  # noqa: E402

    async def probe():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        factory = get_session_factory()

        # seed user
        from app.models.user import User
        async with factory() as s:
            s.add(User(email="probe@example.com", is_active=True))
            await s.commit()
            from sqlalchemy import select
            uid = (await s.execute(select(User.id))).scalar_one()
        print(f"[seed] user_id={uid}")

        # 1. Conversation create
        try:
            async with factory() as s:
                svc = ConversationService(s)
                resp = await svc.create(uid, ConversationCreate(external_id="c1", hr_name="HR张", job_title="后端"))
                print(f"[conversation] OK id={resp.id} status={resp.status}")
                await s.commit()
        except Exception as e:
            print(f"[conversation] FAIL {type(e).__name__}: {e}")

        # 2. Job create
        try:
            async with factory() as s:
                svc = JobService(s)
                resp = await svc.create(uid, JobCreate(external_id="j1", title="后端工程师", salary="20-40k"))
                print(f"[job] OK id={resp.id} status={resp.status}")
                await s.commit()
        except Exception as e:
            print(f"[job] FAIL {type(e).__name__}: {e}")

        # 3. HR create
        try:
            async with factory() as s:
                svc = JobService(s)
                resp = await svc.create_hr(uid, HRCreate(external_id="h1", name="HR李"))
                print(f"[hr] OK id={resp.id} name={resp.name}")
                await s.commit()
        except Exception as e:
            print(f"[hr] FAIL {type(e).__name__}: {e}")

        # 4. Memory create
        try:
            async with factory() as s:
                svc = MemoryService(s)
                resp = await svc.add(uid, MemoryCreate(type=MemoryType.FACT, content="测试事实"))
                print(f"[memory] OK id={resp.id} type={resp.type}")
                await s.commit()
        except Exception as e:
            print(f"[memory] FAIL {type(e).__name__}: {e}")

        # 5. Task create (Redis 入队)
        try:
            async with factory() as s:
                from app.service.task import TaskService
                svc = TaskService(s)
                resp = await svc.create(uid, TaskCreate(type=TT.USER_INITIATED))
                print(f"[task] OK id={resp.id} status={resp.status}")
                await s.commit()
        except Exception as e:
            print(f"[task] FAIL {type(e).__name__}: {e}")

        await engine.dispose()

    asyncio.run(probe())
