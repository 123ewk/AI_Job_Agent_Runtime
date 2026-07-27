"""initial schema: 9 张核心表

Revision ID: 0001
Revises:
Create Date: 2026-07-26

依据：docs/AI求职Agent_设计文档_V2.0/09-数据库Schema设计.md
表：users / tasks / conversations / messages / jobs / resumes / approvals /
    sync_records / execution_logs
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector 扩展：简历向量与语义匹配依赖
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---------------- users ----------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("nickname", sa.String(length=100), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
        sa.Column("llm_api_key_encrypted", sa.String(length=500), nullable=True),
        sa.Column("settings", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---------------- jobs ----------------
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("salary", sa.String(length=100), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("requirements", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("score_detail", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("extra", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_jobs_user_id"),
        sa.UniqueConstraint("platform", "external_id", name="uq_jobs_platform_external"),
        sa.CheckConstraint(
            "status IN ('discovered','analyzed','applied','rejected')",
            name="ck_jobs_status",
        ),
    )
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])

    # ---------------- conversations ----------------
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column(
            "uuid",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("hr_name", sa.String(length=100), nullable=True),
        sa.Column("job_title", sa.String(length=200), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_conversations_user_id"),
        sa.UniqueConstraint("platform", "external_id", name="uq_conversations_platform_external"),
        sa.CheckConstraint(
            "platform IN ('boss','lagou','51job')",
            name="ck_conversations_platform",
        ),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    # ---------------- tasks ----------------
    op.create_table(
        "tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("result", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_tasks_user_id"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name="fk_tasks_conversation_id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_tasks_job_id"),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','WAITING_APPROVAL','WAITING_HR','COMPLETED','FAILED','CANCELLED')",
            name="ck_tasks_status",
        ),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_user_status", "tasks", ["user_id", "status"])
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])

    # ---------------- messages ----------------
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_msg_id", sa.String(length=100), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name="fk_messages_conversation_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_messages_user_id"),
        sa.CheckConstraint("role IN ('user','agent','hr','system')", name="ck_messages_role"),
        sa.CheckConstraint("source IN ('manual','agent','history')", name="ck_messages_source"),
    )
    op.create_index("ix_messages_conversation_sent", "messages", ["conversation_id", "sent_at"])
    op.create_index("ix_messages_user_id", "messages", ["user_id"])
    op.create_index("ix_messages_external_msg_id", "messages", ["external_msg_id"])

    # ---------------- resumes ----------------
    op.create_table(
        "resumes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("file_key", sa.String(length=255), nullable=True),
        sa.Column("file_url", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(512), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_resumes_user_id"),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])

    # ---------------- approvals ----------------
    op.create_table(
        "approvals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_approvals_task_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_approvals_user_id"),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','EXPIRED')", name="ck_approvals_status"),
    )
    op.create_index("ix_approvals_task_id", "approvals", ["task_id"])
    op.create_index("ix_approvals_user_status", "approvals", ["user_id", "status"])

    # ---------------- sync_records ----------------
    op.create_table(
        "sync_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'running'")),
        sa.Column("messages_synced", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_sync_records_user_id"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name="fk_sync_records_conversation_id"),
        sa.CheckConstraint("mode IN ('initial','manual','incremental')", name="ck_sync_records_mode"),
        sa.CheckConstraint("status IN ('running','completed','failed')", name="ck_sync_records_status"),
    )
    op.create_index("ix_sync_records_user_id", "sync_records", ["user_id"])

    # ---------------- execution_logs ----------------
    op.create_table(
        "execution_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("node", sa.String(length=100), nullable=True),
        sa.Column("tool", sa.String(length=100), nullable=True),
        sa.Column("input", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("output", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_execution_logs_task_id"),
    )
    op.create_index("ix_execution_logs_task_created", "execution_logs", ["task_id", "created_at"])


def downgrade() -> None:
    # 按依赖逆序删除
    op.drop_table("execution_logs")
    op.drop_table("sync_records")
    op.drop_table("approvals")
    op.drop_table("resumes")
    op.drop_table("messages")
    op.drop_table("tasks")
    op.drop_table("conversations")
    op.drop_table("jobs")
    op.drop_table("users")
    # vector 扩展可能被其他对象依赖，仅在其为本次创建时删除；保守起见保留扩展。
