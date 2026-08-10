"""职位域 Schema 定义。

字段命名与 ORM Model（app.models.job.Job）+ V2.0 设计文档（doc 05/08/09）保持一致：
- external_id：平台侧职位 ID（去重锚点），非 platform_job_id
- description：职位描述，非 job_description
- score：匹配评分，非 match_score
- status：discovered/scored/chatting/applied/rejected/closed/skipped
HR 同理用 external_id（非 platform_hr_id）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schema.common import BaseSchema
from app.schema.enums import JobStatus


class JobBase(BaseSchema):
    """职位基础字段（与 Job Model 列对齐）。"""

    platform: str = Field("boss", description="平台标识", max_length=30)
    external_id: str = Field(..., description="平台侧职位 ID（去重锚点）", max_length=100)
    title: str | None = Field(None, description="职位名称", max_length=300)
    company: str | None = Field(None, description="公司名称", max_length=200)
    salary: str | None = Field(None, description="薪资范围", max_length=100)
    location: str | None = Field(None, description="工作地点", max_length=200)
    description: str | None = Field(None, description="职位描述")
    source_url: str | None = Field(None, description="职位来源链接", max_length=500)


class JobCreate(JobBase):
    """创建职位请求。"""

    hr_id: int | None = Field(None, description="关联 HR ID")


class JobUpdate(BaseSchema):
    """更新职位请求（部分更新）。"""

    title: str | None = Field(None, max_length=300)
    company: str | None = Field(None, max_length=200)
    salary: str | None = Field(None, max_length=100)
    location: str | None = Field(None, max_length=200)
    description: str | None = Field(None)
    status: JobStatus | None = Field(None, description="职位状态")
    score: float | None = Field(None, ge=0.0, description="匹配评分")
    source_url: str | None = Field(None, max_length=500)


class JobResponse(JobBase):
    """职位信息响应。"""

    id: int = Field(..., description="职位 ID")
    user_id: int = Field(..., description="用户 ID")
    hr_id: int | None = Field(None, description="关联 HR ID")
    status: JobStatus = Field(..., description="职位状态")
    score: float | None = Field(None, description="匹配评分")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class JobFilterParams(BaseSchema):
    """职位筛选参数。"""

    status: JobStatus | None = Field(None, description="按状态筛选")
    keyword: str | None = Field(None, description="关键词搜索（职位名称/公司名）")
    min_score: float | None = Field(None, ge=0.0, description="最低匹配评分")
    platform: str | None = Field(None, description="按平台筛选")


class HRCreate(BaseSchema):
    """创建 HR 请求（与 HR Model 列对齐：external_id 去重锚点）。"""

    platform: str = Field("boss", description="平台标识", max_length=30)
    external_id: str = Field(..., description="平台侧 HR ID（去重锚点）", max_length=100)
    name: str | None = Field(None, description="HR 姓名", max_length=100)
    company: str | None = Field(None, description="公司名称", max_length=200)
    position: str | None = Field(None, description="HR 职位", max_length=200)


class HRResponse(HRCreate):
    """HR 信息响应。"""

    id: int = Field(..., description="HR ID")
    user_id: int = Field(..., description="用户 ID")
    created_at: datetime = Field(..., description="创建时间")
