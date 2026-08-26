"""配置域 Schema 定义。

按域拆分配置：
- llm: LLM 提供商与模型配置
- job_rule: 求职规则（薪资、地点、加班等）
- agent: Agent 行为配置（并发数、自动回复开关等）
- reply_style: 回复风格参数
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.schema.common import BaseSchema


class SettingItem(BaseSchema):
    """单个配置项。"""

    key: str = Field(..., description="配置键名")
    value: Any = Field(..., description="配置值（JSON 类型）")


class SettingCategoryResponse(BaseSchema):
    """某一分类下的所有配置。"""

    category: str = Field(..., description="配置分类")
    settings: list[SettingItem] = Field(..., description="配置项列表")


class SettingBatchUpdate(BaseSchema):
    """批量更新配置请求。

    支持同一分类下多个键值一次性更新，Service 层做事务保证。
    """

    category: str = Field(..., description="配置分类")
    updates: list[SettingItem] = Field(..., description="待更新的配置项列表")

    @field_validator("updates")
    @classmethod
    def validate_settings_not_empty(cls, v: list[SettingItem]) -> list[SettingItem]:
        """确保配置项列表非空。"""
        if not v:
            raise ValueError("配置项列表不能为空")
        return v


# -----------------------------------------------------------------------------
# LLM 配置（category = "llm"）
# -----------------------------------------------------------------------------

class LLMConfigUpdate(BaseSchema):
    """LLM 配置更新请求。

    支持多提供商配置，Service 层统一拆分为 SettingItem。
    """

    provider: str = Field("openai", description="LLM 提供商")
    base_url: str | None = Field(None, description="API Base URL（兼容代理场景）")
    model: str = Field("gpt-4o-mini", description="模型名称")
    api_key: str = Field(..., description="API Key（加密存储）")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int | None = Field(None, ge=1, description="最大生成长度")


class LLMConfigResponse(BaseSchema):
    """LLM 配置响应。

    注意：不返回 api_key 明文，仅返回掩码后的标识。
    """

    provider: str = Field(..., description="LLM 提供商")
    base_url: str | None = Field(None, description="API Base URL")
    model: str = Field(..., description="模型名称")
    api_key_masked: str | None = Field(None, description="API Key 掩码（如 sk-...xxxx）")
    temperature: float = Field(..., description="采样温度")


# -----------------------------------------------------------------------------
# Agent 配置（category = "agent"）
# -----------------------------------------------------------------------------

class AgentConfigUpdate(BaseSchema):
    """Agent 行为配置更新请求。"""

    concurrency_limit: int = Field(3, ge=1, le=10, description="并发任务数限制")
    auto_reply_enabled: bool = Field(False, description="是否启用自动回复")
    auto_approval_threshold: float = Field(0.9, ge=0.0, le=1.0, description="自动确认置信度阈值")
    approval_timeout_seconds: int = Field(20, ge=10, le=120, description="人工确认超时时间（秒）")
    max_retries: int = Field(2, ge=0, le=5, description="任务失败最大重试次数")


class AgentConfigResponse(BaseSchema):
    """Agent 行为配置响应。"""

    concurrency_limit: int = Field(..., description="并发任务数限制")
    auto_reply_enabled: bool = Field(..., description="是否启用自动回复")
    auto_approval_threshold: float = Field(..., description="自动确认置信度阈值")
    approval_timeout_seconds: int = Field(..., description="人工确认超时时间（秒）")
    max_retries: int = Field(..., description="任务失败最大重试次数")


# -----------------------------------------------------------------------------
# 求职规则配置（category = "job_rule"）
# -----------------------------------------------------------------------------

class JobRuleConfigUpdate(BaseSchema):
    """求职规则配置更新请求。"""

    min_salary: int | None = Field(None, ge=0, description="最低期望月薪（K）")
    max_salary: int | None = Field(None, ge=0, description="最高期望月薪（K）")
    preferred_locations: list[str] | None = Field(None, description="期望地点列表")
    overtime_allowed: bool = Field(False, description="是否接受加班")
    outsourcing_allowed: bool = Field(False, description="是否接受外包")
    offsite_allowed: bool = Field(False, description="是否接受异地办公")


class JobRuleConfigResponse(BaseSchema):
    """求职规则配置响应。"""

    min_salary: int | None = Field(None, description="最低期望月薪（K）")
    max_salary: int | None = Field(None, description="最高期望月薪（K）")
    preferred_locations: list[str] | None = Field(None, description="期望地点列表")
    overtime_allowed: bool = Field(..., description="是否接受加班")
    outsourcing_allowed: bool = Field(..., description="是否接受外包")
    offsite_allowed: bool = Field(..., description="是否接受异地办公")


# -----------------------------------------------------------------------------
# 回复风格配置（category = "reply_style"）
# -----------------------------------------------------------------------------

class ReplyStyleConfigUpdate(BaseSchema):
    """回复风格配置更新请求。"""

    tone: str = Field("professional", description="语气：professional / friendly / concise")
    formality: str = Field("formal", description="正式程度：formal / neutral / casual")
    length_preference: str = Field("medium", description="长度偏好：short / medium / long")
    include_greeting: bool = Field(True, description="是否包含问候语")
    include_closing: bool = Field(True, description="是否包含结束语")


class ReplyStyleConfigResponse(BaseSchema):
    """回复风格配置响应。"""

    tone: str = Field(..., description="语气")
    formality: str = Field(..., description="正式程度")
    length_preference: str = Field(..., description="长度偏好")
    include_greeting: bool = Field(..., description="是否包含问候语")
    include_closing: bool = Field(..., description="是否包含结束语")


# -----------------------------------------------------------------------------
# 活动配置推送（方案 A：扩展 local-first → 后端进程内注册表）
# -----------------------------------------------------------------------------

class ActiveConfigPush(BaseSchema):
    """活动配置推送体（POST /settings/active，仅限本机）。

    扩展在设置变更 / 建 WS 连接时，把当前活动的 LLM / 求职规则 / 回复风格
    推给后端注册表，供 Agent 运行时读取（不再查 DB 设置）。
    注意：llm.api_key 为**明文**，只落注册表内存；后端绝无 GET/读回接口
    能将其吐出，也绝不写回任何持久化。
    """

    llm: LLMConfigUpdate | None = Field(None, description="活动 LLM 配置")
    job_rule: JobRuleConfigUpdate | None = Field(None, description="活动求职规则")
    reply_style: ReplyStyleConfigUpdate | None = Field(None, description="活动回复风格")
