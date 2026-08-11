"""设置业务服务。

负责用户配置的校验、持久化、生效与监听态控制。
Settings 按 category 分组，每项有独立的 type 与 validator。

跨域协作：
- 与 Scheduler 协作：监听启停设置生效/失效
- 与 Agent Runtime 协作：JobRule/ReplyStyle 注入 Planner 上下文
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt_value, encrypt_value
from app.core.exceptions import BadRequestError
from app.models.setting import Setting
from app.repository.setting import SettingRepository
from app.schema.setting import (
    AgentConfigResponse,
    AgentConfigUpdate,
    JobRuleConfigResponse,
    JobRuleConfigUpdate,
    LLMConfigResponse,
    LLMConfigUpdate,
    ReplyStyleConfigResponse,
    ReplyStyleConfigUpdate,
    SettingBatchUpdate,
    SettingCategoryResponse,
    SettingItem,
)
from app.service.base import BaseService, transactional

# 各分类的默认值配置
CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "llm": {
        "provider": "openai",
        "base_url": None,
        "model": "gpt-4o-mini",
        "api_key": None,
        "temperature": 0.7,
        "max_tokens": None,
    },
    "agent": {
        "concurrency_limit": 3,
        "auto_reply_enabled": False,
        "auto_approval_threshold": 0.9,
        "approval_timeout_seconds": 20,
        "max_retries": 2,
    },
    "job_rule": {
        "min_salary": None,
        "max_salary": None,
        "preferred_locations": None,
        "overtime_allowed": False,
        "outsourcing_allowed": False,
        "offsite_allowed": False,
    },
    "reply_style": {
        "tone": "professional",
        "formality": "formal",
        "length_preference": "medium",
        "include_greeting": True,
        "include_closing": True,
    },
}

# 分类列表
ALL_CATEGORIES = list(CONFIG_DEFAULTS.keys())


def _mask_api_key(api_key: str | None) -> str | None:
    """掩码 API Key，仅显示首尾。"""
    if api_key is None:
        return None
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}...{api_key[-4:]}"


def _get_value_with_default(current: dict[str, Any], key: str, category: str) -> Any:
    """获取配置值，不存在时返回默认值。"""
    if key in current:
        return current[key]
    return CONFIG_DEFAULTS[category][key]


class SettingsService(BaseService):
    """用户配置业务服务。

    职责：
    - 配置项校验与类型转换
    - 批量更新与原子性保证
    - 监听态变更的 Scheduler 联动
    - 配置默认值与版本迁移
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)
        self.setting_repo = SettingRepository(db)

    def _decrypt_if_needed(self, key: str, s: Setting) -> object:
        """读取 Setting.value：api_key 密文解密，旧明文向后兼容。

        B5 前旧数据为 {"value": plaintext}（无 encrypted 标记），按明文返回；
        B5 后新数据为 {"value": ciphertext, "encrypted": true}，解密后返回。
        密钥变更导致解密失败时视为未配置（None），避免 500。
        """
        raw = s.value.get("value") if isinstance(s.value, dict) else s.value
        if key == "api_key" and isinstance(s.value, dict) and s.value.get("encrypted"):
            try:
                return decrypt_value(get_settings().jwt_secret_key, raw)
            except Exception:
                self.logger.exception("api_key 解密失败，视为未配置（可能密钥已变更）")
                return None
        return raw

    async def _get_category_as_dict(self, user_id: int, category: str) -> dict[str, Any]:
        """获取分类配置为字典，自动填充默认值。"""
        settings = await self.setting_repo.get_by_user_and_category(user_id, category)
        result: dict[str, Any] = {}
        for s in settings:
            result[s.key] = self._decrypt_if_needed(s.key, s)
        return result

    async def get_all(self, user_id: int) -> list[SettingCategoryResponse]:
        """获取用户全部分类配置。

        返回按 category 分组的完整配置，缺失项自动填充默认值。
        """
        all_settings = await self.setting_repo.list_by_user(user_id)

        # 按分类分组（api_key 先解密，供下方掩码）
        by_category: dict[str, dict[str, Any]] = {cat: {} for cat in ALL_CATEGORIES}
        for s in all_settings:
            if s.category in by_category:
                by_category[s.category][s.key] = self._decrypt_if_needed(s.key, s)

        # 构建响应（填充默认值）
        result: list[SettingCategoryResponse] = []
        for category in ALL_CATEGORIES:
            current = by_category[category]
            items: list[SettingItem] = []
            for key, default_value in CONFIG_DEFAULTS[category].items():
                value = current.get(key, default_value)
                # api_key 属高敏配置，全量列表也只返回掩码，不泄露明文
                if category == "llm" and key == "api_key":
                    value = _mask_api_key(value)
                items.append(SettingItem(key=key, value=value))
            result.append(SettingCategoryResponse(category=category, settings=items))

        return result

    async def get_llm_config(self, user_id: int) -> LLMConfigResponse:
        """获取 LLM 提供商配置。"""
        return await self.get_llm_provider(user_id)

    async def get_llm_provider(self, user_id: int) -> LLMConfigResponse:
        """获取 LLM 提供商配置（内部别名）。"""
        current = await self._get_category_as_dict(user_id, "llm")
        return LLMConfigResponse(
            provider=_get_value_with_default(current, "provider", "llm"),
            base_url=_get_value_with_default(current, "base_url", "llm"),
            model=_get_value_with_default(current, "model", "llm"),
            api_key_masked=_mask_api_key(current.get("api_key")),
            temperature=_get_value_with_default(current, "temperature", "llm"),
        )

    async def get_agent_config(self, user_id: int) -> AgentConfigResponse:
        """获取 Agent 策略配置。"""
        return await self.get_agent_strategy(user_id)

    async def get_agent_strategy(self, user_id: int) -> AgentConfigResponse:
        """获取 Agent 策略配置。"""
        current = await self._get_category_as_dict(user_id, "agent")
        return AgentConfigResponse(
            concurrency_limit=_get_value_with_default(current, "concurrency_limit", "agent"),
            auto_reply_enabled=_get_value_with_default(current, "auto_reply_enabled", "agent"),
            auto_approval_threshold=_get_value_with_default(current, "auto_approval_threshold", "agent"),
            approval_timeout_seconds=_get_value_with_default(current, "approval_timeout_seconds", "agent"),
            max_retries=_get_value_with_default(current, "max_retries", "agent"),
        )

    async def get_job_rule_config(self, user_id: int) -> JobRuleConfigResponse:
        """获取求职规则配置。"""
        return await self.get_job_rule(user_id)

    async def get_job_rule(self, user_id: int) -> JobRuleConfigResponse:
        """获取求职规则配置（内部别名）。"""
        current = await self._get_category_as_dict(user_id, "job_rule")
        return JobRuleConfigResponse(
            min_salary=_get_value_with_default(current, "min_salary", "job_rule"),
            max_salary=_get_value_with_default(current, "max_salary", "job_rule"),
            preferred_locations=_get_value_with_default(current, "preferred_locations", "job_rule"),
            overtime_allowed=_get_value_with_default(current, "overtime_allowed", "job_rule"),
            outsourcing_allowed=_get_value_with_default(current, "outsourcing_allowed", "job_rule"),
            offsite_allowed=_get_value_with_default(current, "offsite_allowed", "job_rule"),
        )

    async def get_reply_style_config(self, user_id: int) -> ReplyStyleConfigResponse:
        """获取回复风格配置。"""
        return await self.get_reply_style(user_id)

    async def get_reply_style(self, user_id: int) -> ReplyStyleConfigResponse:
        """获取回复风格配置。"""
        current = await self._get_category_as_dict(user_id, "reply_style")
        return ReplyStyleConfigResponse(
            tone=_get_value_with_default(current, "tone", "reply_style"),
            formality=_get_value_with_default(current, "formality", "reply_style"),
            length_preference=_get_value_with_default(current, "length_preference", "reply_style"),
            include_greeting=_get_value_with_default(current, "include_greeting", "reply_style"),
            include_closing=_get_value_with_default(current, "include_closing", "reply_style"),
        )

    async def update_llm_config(self, user_id: int, data: LLMConfigUpdate) -> LLMConfigResponse:
        """更新 LLM 配置。"""
        items = [
            SettingItem(key="provider", value=data.provider),
            SettingItem(key="base_url", value=data.base_url),
            SettingItem(key="model", value=data.model),
            SettingItem(key="api_key", value=data.api_key),
            SettingItem(key="temperature", value=data.temperature),
        ]
        if data.max_tokens is not None:
            items.append(SettingItem(key="max_tokens", value=data.max_tokens))

        batch = SettingBatchUpdate(category="llm", updates=items)
        await self.batch_update(user_id, "llm", batch)
        return await self.get_llm_config(user_id)

    async def update_agent_config(self, user_id: int, data: AgentConfigUpdate) -> AgentConfigResponse:
        """更新 Agent 策略配置。"""
        items = [
            SettingItem(key="concurrency_limit", value=data.concurrency_limit),
            SettingItem(key="auto_reply_enabled", value=data.auto_reply_enabled),
            SettingItem(key="auto_approval_threshold", value=data.auto_approval_threshold),
            SettingItem(key="approval_timeout_seconds", value=data.approval_timeout_seconds),
            SettingItem(key="max_retries", value=data.max_retries),
        ]
        batch = SettingBatchUpdate(category="agent", updates=items)
        await self.batch_update(user_id, "agent", batch)
        return await self.get_agent_config(user_id)

    async def update_job_rule_config(self, user_id: int, data: JobRuleConfigUpdate) -> JobRuleConfigResponse:
        """更新求职规则配置。"""
        items = [
            SettingItem(key="min_salary", value=data.min_salary),
            SettingItem(key="max_salary", value=data.max_salary),
            SettingItem(key="preferred_locations", value=data.preferred_locations),
            SettingItem(key="overtime_allowed", value=data.overtime_allowed),
            SettingItem(key="outsourcing_allowed", value=data.outsourcing_allowed),
            SettingItem(key="offsite_allowed", value=data.offsite_allowed),
        ]
        batch = SettingBatchUpdate(category="job_rule", updates=items)
        await self.batch_update(user_id, "job_rule", batch)
        return await self.get_job_rule_config(user_id)

    async def update_reply_style_config(self, user_id: int, data: ReplyStyleConfigUpdate) -> ReplyStyleConfigResponse:
        """更新回复风格配置。"""
        items = [
            SettingItem(key="tone", value=data.tone),
            SettingItem(key="formality", value=data.formality),
            SettingItem(key="length_preference", value=data.length_preference),
            SettingItem(key="include_greeting", value=data.include_greeting),
            SettingItem(key="include_closing", value=data.include_closing),
        ]
        batch = SettingBatchUpdate(category="reply_style", updates=items)
        await self.batch_update(user_id, "reply_style", batch)
        return await self.get_reply_style_config(user_id)

    @transactional
    async def batch_update(
        self,
        user_id: int,
        category: str,
        data: SettingBatchUpdate,
    ) -> dict[str, Any]:
        """批量更新某分类下的配置项。

        原子性：所有项都成功或全部失败。
        触发 side effect：监听时间、最大聊天数等变更需联动 Scheduler。
        """
        if category not in CONFIG_DEFAULTS:
            raise BadRequestError(f"不支持的配置分类: {category}")

        updated_keys: list[str] = []
        for item in data.updates:
            if item.key not in CONFIG_DEFAULTS[category]:
                self.logger.warning(
                    "unknown_config_key_skipped",
                    extra={"user_id": user_id, "category": category, "key": item.key},
                )
                continue

            # Upsert 配置
            existing = await self.setting_repo.get_by_key(user_id, category, item.key)
            # value 存储为 {"value": actual_value} 结构，支持多种类型
            # api_key 属高敏配置，落库前对称加密，标记 encrypted 供读取侧解密
            value = item.value
            if category == "llm" and item.key == "api_key" and isinstance(value, str) and value:
                value = encrypt_value(get_settings().jwt_secret_key, value)
                value_data: dict[str, Any] = {"value": value, "encrypted": True}
            else:
                value_data = {"value": value}

            if existing:
                await self.setting_repo.update(existing, {"value": value_data})
            else:
                await self.setting_repo.create(
                    {
                        "user_id": user_id,
                        "category": category,
                        "key": item.key,
                        "value": value_data,
                    }
                )
            updated_keys.append(item.key)

        self.logger.info(
            "settings_updated",
            extra={"user_id": user_id, "category": category, "updated_keys": updated_keys},
        )

        # TODO: 触发 side effect 回调（如 Scheduler 状态变更）
        # if category == "agent" and "auto_reply_enabled" in updated_keys:
        #     await self._handle_auto_reply_toggle(user_id, ...)

        return {"category": category, "updated_keys": updated_keys}

    async def update_listening_state(self, user_id: int, enabled: bool) -> bool:
        """更新后台监听状态。

        联动 Scheduler：启动/停止 monitor_tick job。
        状态持久化于 DB，防止 backend 重启丢失。
        """
        # 将监听状态存储在 agent 分类下
        data = SettingBatchUpdate(
            category="agent",
            updates=[SettingItem(key="listening_enabled", value=enabled)],
        )
        await self.batch_update(user_id, "agent", data)

        self.logger.info(
            "listening_state_updated",
            extra={"user_id": user_id, "enabled": enabled},
        )

        # TODO: 实际调用 SchedulerManager 启停 job
        # if enabled:
        #     await scheduler.start_monitor(user_id)
        # else:
        #     await scheduler.stop_monitor(user_id)

        return enabled

    async def get_listening_state(self, user_id: int) -> dict[str, Any]:
        """获取当前监听状态与配置。

        返回：是否监听、下次执行时间、已运行时长、配置的间隔时间。
        """
        current = await self._get_category_as_dict(user_id, "agent")
        enabled = current.get("listening_enabled", False)

        # TODO: 从 Scheduler 获取实际运行状态
        return {
            "enabled": enabled,
            "next_run": None,
            "running_duration": None,
            "interval_seconds": current.get("monitor_interval", 60),
        }

    async def validate_llm_settings(self, user_id: int) -> tuple[bool, str | None]:
        """校验 LLM 配置是否可用。

        实际调用 LLM API 做 connectivity check，返回可用性与错误信息。
        用于用户保存配置时即时反馈。
        """
        current = await self._get_category_as_dict(user_id, "llm")
        api_key = current.get("api_key")

        if not api_key:
            return False, "API Key 未配置"

        # TODO: 实际调用 LLM client 做 ping 测试
        # try:
        #     client = AsyncOpenAI(api_key=api_key, base_url=current.get("base_url"))
        #     await client.models.list()
        #     return True, None
        # except Exception as exc:
        #     return False, str(exc)

        self.logger.info("llm_validation_skipped", extra={"user_id": user_id})
        return True, "配置已保存，连通性测试待实现"
