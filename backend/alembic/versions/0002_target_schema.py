"""target schema: 14 表目标态（9 -> 14）

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-29

依据：docs/AI求职Agent_设计文档_V2.0/09-数据库Schema设计.md §5 / §9
- 新增 5 表：settings / hrs / resume_summaries / memory / task_checkpoint_index
- 列扩展：users / jobs / conversations / tasks / resumes / approvals / execution_logs
- 枚举迁移：jobs.status / tasks.status / approvals.status（先扩后缩）
- 默认值：tasks.max_retries 3 -> 2
- 数据回填：users.settings JSONB -> settings / resumes.embedding -> resume_summaries
            / conversations.hr_name -> hrs
- 新增索引：含向量 ivfflat、部分索引

迁移原则：向后兼容；枚举先扩后缩；数据回填幂等；每步可回滚。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# 枚举：旧值 -> 新值 映射（upgrade 方向）
# ---------------------------------------------------------------------------
# 全小写，与 doc 09 §7 对齐
JOBS_STATUS_MAP = {
    "discovered": "discovered",
    "analyzed": "scored",       # analyzed 重命名为 scored
    "applied": "applied",
    "rejected": "rejected",
}
# 新枚举全部值
JOBS_STATUS_NEW = (
    "discovered",
    "scored",
    "chatting",
    "applied",
    "rejected",
    "closed",
    "skipped",
)

# tasks: 旧大写 -> 新小写 + 值映射
TASKS_STATUS_MAP = {
    "PENDING": "pending",
    "RUNNING": "running",
    "WAITING_APPROVAL": "waiting_approval",
    "WAITING_HR": "waiting_approval",   # 合并入 waiting_approval
    "COMPLETED": "succeeded",
    "FAILED": "failed",
    "CANCELLED": "canceled",
}
TASKS_STATUS_NEW = (
    "pending",
    "running",
    "waiting_approval",
    "recovering",
    "succeeded",
    "failed",
    "canceled",
)

# approvals: 旧大写 -> 新小写
APPROVALS_STATUS_MAP = {
    "PENDING": "pending",
    "APPROVED": "approved",
    "REJECTED": "denied",           # REJECTED -> denied
    "EXPIRED": "timed_out",         # EXPIRED -> timed_out
}
APPROVALS_STATUS_NEW = (
    "pending",
    "approved",
    "denied",
    "timed_out",
)


def _check_in(name: str, values: tuple[str, ...]) -> str:
    """构造 CHECK 约束表达式。"""
    quoted = ",".join(f"'{v}'" for v in values)
    return f"status IN ({quoted})"


def upgrade() -> None:
    # ================================================================
    # STEP 1: 新增 5 张表（doc 09 §5.2 / 5.3 / 5.9 / 5.10 / 5.14）
    #         先建表再做列扩展和数据迁移，避免 FK 依赖问题
    # ================================================================

    # ---------------- settings ----------------
    op.create_table(
        "settings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_settings_user_id", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "category", "key", name="uq_settings_user_cat_key"),
        sa.CheckConstraint(
            "category IN ('llm','job_rule','agent','reply_style')",
            name="ck_settings_category",
        ),
    )
    op.create_index("ix_settings_user", "settings", ["user_id"])

    # ---------------- hrs ----------------
    op.create_table(
        "hrs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False, server_default=sa.text("'boss'")),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("position", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_hrs_user_id", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "platform", "external_id", name="uq_hrs_user_platform_ext"),
    )
    op.create_index("ix_hrs_user", "hrs", ["user_id"])

    # ---------------- resume_summaries ----------------
    op.create_table(
        "resume_summaries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("resume_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], name="fk_resume_summaries_resume_id", ondelete="CASCADE"),
        sa.UniqueConstraint("resume_id", "version", name="uq_resume_summary_resume_version"),
    )
    op.create_index("ix_resume_summaries_resume", "resume_summaries", ["resume_id"])
    # ivfflat 向量索引（数据量小时先建，lists=100）
    op.execute(
        "CREATE INDEX ix_resume_summaries_embedding "
        "ON resume_summaries USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )

    # ---------------- memory ----------------
    op.create_table(
        "memory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_memory_user_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"],
            name="fk_memory_conversation_id",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_memory_job_id"),
        sa.CheckConstraint(
            "type IN ('preference','hr_pact','interview','decision','fact')",
            name="ck_memory_type",
        ),
    )
    op.create_index("ix_memory_user", "memory", ["user_id"])
    op.create_index("ix_memory_user_conv", "memory", ["user_id", "conversation_id"])
    op.execute(
        "CREATE INDEX ix_memory_embedding "
        "ON memory USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )

    # ---------------- task_checkpoint_index ----------------
    op.create_table(
        "task_checkpoint_index",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"],
            name="fk_task_checkpoint_index_task_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_chk_task", "task_checkpoint_index", ["task_id"])
    op.create_index("ix_chk_thread", "task_checkpoint_index", ["thread_id"])

    # ================================================================
    # STEP 2: 列扩展（全部可空 / 有默认值，向后兼容）
    # ================================================================

    # --- users ---
    op.add_column("users", sa.Column("llm_base_url", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("llm_model", sa.String(length=100), nullable=True))

    # --- jobs ---
    op.add_column("jobs", sa.Column("hr_id", sa.BigInteger(), nullable=True))
    op.add_column("jobs", sa.Column("source_url", sa.String(length=500), nullable=True))
    op.create_foreign_key("fk_jobs_hr_id", "jobs", "hrs", ["hr_id"], ["id"])

    # --- conversations ---
    op.add_column("conversations", sa.Column("job_id", sa.BigInteger(), nullable=True))
    op.add_column("conversations", sa.Column("hr_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column(
            "thread_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'active'")),
    )
    op.add_column("conversations", sa.Column("external_chat_id", sa.String(length=100), nullable=True))
    op.create_foreign_key("fk_conversations_job_id", "conversations", "jobs", ["job_id"], ["id"])
    op.create_foreign_key("fk_conversations_hr_id", "conversations", "hrs", ["hr_id"], ["id"])
    op.create_unique_constraint("uq_conversations_uuid", "conversations", ["uuid"])
    op.create_unique_constraint("uq_conversations_job_id", "conversations", ["job_id"])
    op.create_index("ix_conversations_user_status", "conversations", ["user_id", "status"])
    op.create_index("ix_conversations_thread_id", "conversations", ["thread_id"])
    # platform CHECK 约束已存在，不改动

    # --- tasks ---
    op.add_column(
        "tasks",
        sa.Column("thread_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("priority", sa.String(length=5), nullable=False, server_default=sa.text("'P2'")),
    )
    op.create_index("ix_tasks_thread_id", "tasks", ["thread_id"])
    op.create_index("ix_tasks_priority_scheduled", "tasks", ["priority", "scheduled_at"])
    # max_retries 默认值 3 -> 2（仅改默认，不回填已有行）
    op.alter_column("tasks", "max_retries", server_default=sa.text("2"))
    # priority CHECK 约束
    op.create_check_constraint(
        "ck_tasks_priority",
        "tasks",
        "priority IN ('P0','P1','P2','P3')",
    )

    # --- resumes ---
    op.add_column(
        "resumes",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "resumes",
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
    )
    op.create_check_constraint(
        "ck_resumes_status",
        "resumes",
        "status IN ('draft','active','archived')",
    )

    # --- approvals ---
    op.add_column("approvals", sa.Column("decision", sa.String(length=20), nullable=True))

    # --- execution_logs ---
    op.add_column(
        "execution_logs",
        sa.Column("trace_id", sa.String(length=64), nullable=False, server_default=sa.text("''")),
    )
    op.add_column("execution_logs", sa.Column("skill", sa.String(length=100), nullable=True))
    op.create_index("ix_execution_logs_trace_id", "execution_logs", ["trace_id"])

    # ================================================================
    # STEP 3: 枚举迁移（先扩后缩原则）
    #   3.1 删除旧 CHECK 约束
    #   3.2 数据映射 UPDATE
    #   3.3 建新 CHECK 约束
    # ================================================================

    # --- jobs.status: analyzed -> scored; + chatting/closed/skipped ---
    # 枚举值为代码内白名单常量，直接拼接 SQL 安全且简洁。
    op.drop_constraint("ck_jobs_status", "jobs", type_="check")
    for old_val, new_val in JOBS_STATUS_MAP.items():
        if old_val != new_val:
            op.execute(f"UPDATE jobs SET status = '{new_val}' WHERE status = '{old_val}'")
    op.create_check_constraint(
        "ck_jobs_status",
        "jobs",
        _check_in("status", JOBS_STATUS_NEW),
    )

    # --- tasks.status: 大小写转换 + 值映射 ---
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    for old_val, new_val in TASKS_STATUS_MAP.items():
        op.execute(f"UPDATE tasks SET status = '{new_val}' WHERE status = '{old_val}'")
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        _check_in("status", TASKS_STATUS_NEW),
    )

    # --- approvals.status: 大小写 + REJECTED->denied / EXPIRED->timed_out ---
    op.drop_constraint("ck_approvals_status", "approvals", type_="check")
    for old_val, new_val in APPROVALS_STATUS_MAP.items():
        op.execute(f"UPDATE approvals SET status = '{new_val}' WHERE status = '{old_val}'")
    op.create_check_constraint(
        "ck_approvals_status",
        "approvals",
        _check_in("status", APPROVALS_STATUS_NEW),
    )

    # ================================================================
    # STEP 4: 数据回填（幂等，可重入）
    # ================================================================

    # 4.1 users.settings JSONB -> settings 表（拆分 category=agent 的键值）
    #     简化策略：将 users.settings 整个 JSONB 逐 key 拆到 category='legacy'
    #     后续 Service 层按需迁移到具体 category
    op.execute(
        """
        INSERT INTO settings (user_id, category, key, value, updated_at)
        SELECT
            u.id AS user_id,
            'legacy' AS category,
            kv.key,
            to_jsonb(kv.value),
            now() AS updated_at
        FROM users u,
             jsonb_each(u.settings) AS kv(key, value)
        ON CONFLICT (user_id, category, key) DO NOTHING
        """
    )

    # 4.2 resumes.embedding -> resume_summaries(version=1)
    #     embedding 非空才迁移；summary 暂时用 content 前 1000 字符占位
    op.execute(
        """
        INSERT INTO resume_summaries (resume_id, version, summary, embedding, created_at)
        SELECT
            r.id AS resume_id,
            1 AS version,
            COALESCE(left(r.content, 1000), 'migrated from resumes.content') AS summary,
            r.embedding,
            now() AS created_at
        FROM resumes r
        WHERE r.embedding IS NOT NULL
        ON CONFLICT (resume_id, version) DO NOTHING
        """
    )

    # 4.3 conversations.hr_name -> hrs（去重反推）
    #     以 user_id + hr_name 为去重键；external_id 留空后续同步补
    op.execute(
        """
        INSERT INTO hrs (user_id, platform, external_id, name, created_at, updated_at)
        SELECT DISTINCT
            c.user_id,
            'boss' AS platform,
            'legacy_' || c.hr_name AS external_id,
            c.hr_name AS name,
            now() AS created_at,
            now() AS updated_at
        FROM conversations c
        WHERE c.hr_name IS NOT NULL
          AND c.hr_name <> ''
        ON CONFLICT (user_id, platform, external_id) DO NOTHING
        """
    )

    # 4.4 回填 conversations.hr_id（按 hr_name 匹配）
    op.execute(
        """
        UPDATE conversations c
        SET hr_id = h.id
        FROM hrs h
        WHERE c.user_id = h.user_id
          AND c.hr_name = h.name
          AND c.hr_id IS NULL
        """
    )

    # ================================================================
    # STEP 5: 新增部分索引（approvals 超时扫描加速）
    # ================================================================
    op.execute(
        "CREATE INDEX ix_approvals_expires_pending "
        "ON approvals(expires_at) WHERE status = 'pending'"
    )

    # 补充 jobs 索引（doc 09 §5.4）
    op.create_index("ix_jobs_user_status", "jobs", ["user_id", "status"])
    op.create_index("ix_jobs_user_score", "jobs", ["user_id", "score"])


def downgrade() -> None:
    """逆序回滚。数据回填不做删除（保守策略，避免数据丢失）；
    枚举映射做近似回退（部分值可能映射不回来，如 WAITING_HR 合并进 waiting_approval）。
    """

    # ================================================================
    # 逆 STEP 5: 删除新增索引
    # ================================================================
    op.drop_index("ix_jobs_user_score", table_name="jobs")
    op.drop_index("ix_jobs_user_status", table_name="jobs")
    op.drop_index("ix_approvals_expires_pending", table_name="approvals")

    # ================================================================
    # 逆 STEP 4: 数据回填不回滚（保守策略，数据保留）
    # ================================================================

    # ================================================================
    # 逆 STEP 3: 枚举回退（先扩后缩的逆：删新 CHECK -> UPDATE 回旧值 -> 建旧 CHECK）
    # ================================================================

    # --- approvals.status ---
    op.drop_constraint("ck_approvals_status", "approvals", type_="check")
    # denied -> REJECTED, timed_out -> EXPIRED，其他恢复大写
    reverse_approval = {v: k for k, v in APPROVALS_STATUS_MAP.items()}
    for new_val, old_val in reverse_approval.items():
        op.execute(f"UPDATE approvals SET status = '{old_val}' WHERE status = '{new_val}'")
    op.create_check_constraint(
        "ck_approvals_status",
        "approvals",
        "status IN ('PENDING','APPROVED','REJECTED','EXPIRED')",
    )

    # --- tasks.status ---
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    # 回退：recovering 没有旧对应，归为 PENDING（最安全）
    op.execute("UPDATE tasks SET status = 'PENDING' WHERE status = 'recovering'")
    # waiting_approval 统一回退为 WAITING_APPROVAL（原 WAITING_HR 信息丢失）
    op.execute("UPDATE tasks SET status = 'WAITING_APPROVAL' WHERE status = 'waiting_approval'")
    reverse_tasks = {v: k for k, v in TASKS_STATUS_MAP.items()}
    for new_val, old_val in reverse_tasks.items():
        if new_val == "waiting_approval":
            continue  # 上面已处理
        op.execute(f"UPDATE tasks SET status = '{old_val}' WHERE status = '{new_val}'")
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('PENDING','RUNNING','WAITING_APPROVAL','WAITING_HR','COMPLETED','FAILED','CANCELLED')",
    )

    # --- jobs.status ---
    op.drop_constraint("ck_jobs_status", "jobs", type_="check")
    # chatting/closed/skipped 回退为 discovered（无对应旧值，归入初始态最安全）
    op.execute("UPDATE jobs SET status = 'discovered' WHERE status IN ('chatting','closed','skipped')")
    # scored -> analyzed
    op.execute("UPDATE jobs SET status = 'analyzed' WHERE status = 'scored'")
    op.create_check_constraint(
        "ck_jobs_status",
        "jobs",
        "status IN ('discovered','analyzed','applied','rejected')",
    )

    # ================================================================
    # 逆 STEP 2: 删除新增列 / 约束 / 索引
    #   注意：按依赖逆序（先删 FK，再删列）
    # ================================================================

    # execution_logs
    op.drop_index("ix_execution_logs_trace_id", table_name="execution_logs")
    op.drop_column("execution_logs", "skill")
    op.drop_column("execution_logs", "trace_id")

    # approvals
    op.drop_column("approvals", "decision")

    # resumes
    op.drop_constraint("ck_resumes_status", "resumes", type_="check")
    op.drop_column("resumes", "status")
    op.drop_column("resumes", "version")

    # tasks
    op.drop_constraint("ck_tasks_priority", "tasks", type_="check")
    op.alter_column("tasks", "max_retries", server_default=sa.text("3"))
    op.drop_index("ix_tasks_priority_scheduled", table_name="tasks")
    op.drop_index("ix_tasks_thread_id", table_name="tasks")
    op.drop_column("tasks", "priority")
    op.drop_column("tasks", "thread_id")

    # conversations
    op.drop_index("ix_conversations_thread_id", table_name="conversations")
    op.drop_index("ix_conversations_user_status", table_name="conversations")
    op.drop_constraint("uq_conversations_job_id", "conversations", type_="unique")
    op.drop_constraint("uq_conversations_uuid", "conversations", type_="unique")
    op.drop_constraint("fk_conversations_hr_id", "conversations", type_="foreignkey")
    op.drop_constraint("fk_conversations_job_id", "conversations", type_="foreignkey")
    op.drop_column("conversations", "external_chat_id")
    op.drop_column("conversations", "status")
    op.drop_column("conversations", "thread_id")
    op.drop_column("conversations", "hr_id")
    op.drop_column("conversations", "job_id")

    # jobs
    op.drop_constraint("fk_jobs_hr_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "source_url")
    op.drop_column("jobs", "hr_id")

    # users
    op.drop_column("users", "llm_model")
    op.drop_column("users", "llm_base_url")

    # ================================================================
    # 逆 STEP 1: 删除新增表（按依赖逆序：有 FK 的先删）
    # ================================================================
    op.drop_table("task_checkpoint_index")
    op.drop_table("memory")
    op.drop_table("resume_summaries")
    op.drop_table("hrs")
    op.drop_table("settings")
