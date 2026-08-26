"""会话域 Schema 定义。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.schema.common import BaseSchema


class ConversationBase(BaseSchema):
    """会话基础字段。"""

    platform: str = Field("boss", description="平台标识", min_length=1, max_length=30)
    external_id: str = Field(
        ..., description="平台侧会话 ID（去重锚点）", min_length=1, max_length=100
    )
    hr_name: str | None = Field(None, description="HR 姓名", max_length=100)
    job_title: str | None = Field(None, description="职位名称", max_length=200)


class ConversationCreate(ConversationBase):
    """创建会话请求。"""

    job_id: int | None = Field(None, description="关联职位 ID")
    hr_id: int | None = Field(None, description="关联 HR ID")


class ConversationUpdate(BaseSchema):
    """更新会话请求。"""

    hr_name: str | None = Field(None, max_length=100)
    job_title: str | None = Field(None, max_length=200)
    status: str | None = Field(None, description="状态：active / waiting_hr / closed", max_length=30)
    last_synced_at: datetime | None = Field(None, description="最后同步时间")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in {"active", "waiting_hr", "closed"}:
            raise ValueError("status 必须是 active / waiting_hr / closed")
        return v


class ConversationResponse(ConversationBase):
    """会话信息响应。"""

    id: int = Field(..., description="会话 ID")
    user_id: int = Field(..., description="用户 ID")
    job_id: int | None = Field(None, description="关联职位 ID")
    hr_id: int | None = Field(None, description="关联 HR ID")
    uuid: UUID = Field(..., description="会话 UUID")
    thread_id: UUID = Field(..., description="LangGraph thread_id")
    status: str = Field(..., description="状态：active / waiting_hr / closed")
    last_synced_at: datetime | None = Field(None, description="最后同步时间")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class MessageBase(BaseSchema):
    """消息基础字段。"""

    external_msg_id: str | None = Field(None, description="平台侧消息 ID（去重用）", max_length=100)
    role: str = Field(..., description="角色：user / hr / agent / system", max_length=20)
    content: str = Field(..., description="消息内容", min_length=1)
    source: str = Field("manual", description="来源：manual / agent / history", max_length=20)
    sent_at: datetime | None = Field(None, description="发送时间")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in {"user", "hr", "agent", "system"}:
            raise ValueError("role 必须是 user / hr / agent / system")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v not in {"manual", "agent", "history"}:
            raise ValueError("source 必须是 manual / agent / history")
        return v


class MessageCreate(MessageBase):
    """创建消息请求。

    conversation_id 为可选：路径参数已携带会话 ID，服务端会强制覆盖。
    保留字段仅为兼容已有调用方，不做为真实输入来源。
    """

    conversation_id: int | None = Field(None, description="会话 ID（由路径参数覆盖）")


class MessageResponse(MessageBase):
    """消息信息响应。"""

    id: int = Field(..., description="消息 ID")
    conversation_id: int = Field(..., description="会话 ID")
    user_id: int = Field(..., description="用户 ID")
    created_at: datetime = Field(..., description="入库时间")
