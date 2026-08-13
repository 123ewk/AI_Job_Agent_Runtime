"""简历域 Schema 定义。"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schema.common import BaseSchema


class ResumeBase(BaseSchema):
    """简历基础字段。

    字段命名与 Resume Model（app.models.resume）+ DB 设计文档 02-简历模块.md 对齐：
    - name 而非 title（Model 为 name，VARCHAR(100)）
    - file_key / file_url 而非 file_name/file_type/file_size（文件对象由 MinIO 托管）
    """

    name: str = Field(..., description="简历名称", max_length=100)
    file_key: str | None = Field(None, description="MinIO 对象 key", max_length=255)
    file_url: str | None = Field(None, description="文件可访问 URL", max_length=500)


class ResumeCreate(ResumeBase):
    """创建简历请求。

    V1 用解析后文本（content）而非 multipart 文件：文件存储（MinIO）与
    文档解析管线尚未接线，如实偏离 doc 10 §12 的 multipart 设计。
    """

    content: str = Field(..., description="简历解析后的文本内容")


class ResumeUpdate(BaseSchema):
    """更新简历请求（部分更新，V1 无对应端点，为后续版本预留）。"""

    name: str | None = Field(None, max_length=100)
    is_default: bool | None = Field(None, description="是否设为默认简历")


class ResumeResponse(BaseSchema):
    """简历信息响应。

    仅返回元信息与摘要预览，不返回完整简历原文（原文走详情接口）。
    """

    id: int = Field(..., description="简历 ID")
    user_id: int = Field(..., description="用户 ID")
    name: str = Field(..., description="简历名称")
    version: int = Field(..., description="版本号")
    status: str = Field(..., description="状态：draft/active/archived")
    is_default: bool = Field(..., description="是否默认简历")
    summary_preview: str | None = Field(
        None, description="简历摘要预览（Agent 摘要管线接线后出现，V1 恒为 None）"
    )
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class ResumeDetailResponse(ResumeResponse):
    """简历详情响应（含解析后原文）。"""

    content: str | None = Field(None, description="简历解析后的文本内容")


class ResumeSummaryResponse(BaseSchema):
    """简历摘要响应。"""

    id: int = Field(..., description="摘要 ID")
    resume_id: int = Field(..., description="简历 ID")
    version: int = Field(..., description="版本号")
    summary: str = Field(..., description="结构化摘要")
    embedding_preview: str | None = Field(None, description="向量预览（前 5 维）")
    created_at: str = Field(..., description="创建时间")
