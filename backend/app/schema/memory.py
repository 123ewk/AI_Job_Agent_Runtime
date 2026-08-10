"""记忆域 Schema 定义。"""

from __future__ import annotations

from pydantic import Field

from app.schema.common import BaseSchema
from app.schema.enums import MemoryType


class MemoryBase(BaseSchema):
    """记忆基础字段。"""

    type: MemoryType = Field(..., description="记忆类型")
    content: str = Field(..., description="记忆内容")


class MemoryCreate(MemoryBase):
    """创建记忆请求。"""

    conversation_id: int | None = Field(None, description="关联会话 ID")
    job_id: int | None = Field(None, description="关联职位 ID")


class MemoryResponse(MemoryBase):
    """记忆信息响应。"""

    id: int = Field(..., description="记忆 ID")
    user_id: int = Field(..., description="用户 ID")
    conversation_id: int | None = Field(None, description="关联会话 ID")
    job_id: int | None = Field(None, description="关联职位 ID")
    similarity_score: float | None = Field(None, description="相似度得分（仅检索时返回）")
    created_at: str = Field(..., description="创建时间")


class MemorySearchRequest(BaseSchema):
    """语义检索请求。"""

    query: str = Field(..., description="检索查询文本", min_length=1)
    top_k: int = Field(10, ge=1, le=50, description="返回结果数量")
    conversation_id: int | None = Field(None, description="限定会话上下文")
    job_id: int | None = Field(None, description="限定职位上下文")
    memory_type: MemoryType | None = Field(None, description="按类型筛选")
