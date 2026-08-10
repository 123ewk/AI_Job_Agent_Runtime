"""简历域 Schema 定义。"""

from __future__ import annotations

from pydantic import Field

from app.schema.common import BaseSchema


class ResumeBase(BaseSchema):
    """简历基础字段。"""

    title: str = Field(..., description="简历标题", max_length=200)
    file_name: str | None = Field(None, description="原始文件名", max_length=255)
    file_type: str | None = Field(None, description="文件类型", max_length=50)
    file_size: int | None = Field(None, description="文件大小（字节）")


class ResumeCreate(ResumeBase):
    """创建简历请求。"""

    content: str = Field(..., description="简历解析后的文本内容")


class ResumeUpdate(BaseSchema):
    """更新简历请求。"""

    title: str | None = Field(None, max_length=200)
    is_default: bool | None = Field(None, description="是否设为默认简历")


class ResumeResponse(ResumeBase):
    """简历信息响应。

    注意：不返回完整简历原文，仅返回元信息和摘要预览。
    """

    id: int = Field(..., description="简历 ID")
    user_id: int = Field(..., description="用户 ID")
    is_default: bool = Field(..., description="是否默认简历")
    summary_preview: str | None = Field(None, description="简历摘要预览（前 200 字）")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


class ResumeSummaryResponse(BaseSchema):
    """简历摘要响应。"""

    id: int = Field(..., description="摘要 ID")
    resume_id: int = Field(..., description="简历 ID")
    version: int = Field(..., description="版本号")
    summary: str = Field(..., description="结构化摘要")
    embedding_preview: str | None = Field(None, description="向量预览（前 5 维）")
    created_at: str = Field(..., description="创建时间")
