"""系统配置路由。

提供 LLM、Agent 策略、求职规则、回复风格四类配置的查询与更新。
所有配置按用户隔离，API key 返回时掩码处理。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import CurrentUserDep, SettingsServiceDep
from app.core.active_config_registry import set_active_config
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.schema.setting import (
    ActiveConfigPush,
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
)

router = APIRouter(prefix="/settings", tags=["settings"])
logger = get_logger("app.api.settings")

# 允许推送活动配置的本机回环地址（方案 A 防泄漏：只收本机明文 api_key）
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1"})


@router.post("/active")
async def push_active_config(request: Request, data: ActiveConfigPush) -> dict:
    """本机限定：接收扩展推送的活动配置，落进程内注册表。

    扩展在设置变更 / 建 WS 连接时调用。接受 llm / job_rule / reply_style
    三段（各段可选），明文 api_key 只进内存注册表，响应不回吐任何 key。
    非本机来源直接拒绝（BadRequestError），防局域网任意机器塞配置。
    """
    host = request.client.host if request.client else ""
    if host not in _LOCAL_HOSTS:
        msg = "仅允许本机推送活动配置"
        raise BadRequestError(msg)

    if data.llm is not None:
        set_active_config("llm", data.llm.model_dump())
    if data.job_rule is not None:
        set_active_config("job_rule", data.job_rule.model_dump())
    if data.reply_style is not None:
        set_active_config("reply_style", data.reply_style.model_dump())

    logger.info("active_config_pushed", extra={"sections": len(
        [x for x in (data.llm, data.job_rule, data.reply_style) if x is not None]
    )})
    return {"status": "ok"}


@router.get("", response_model=list[SettingCategoryResponse])
async def get_all_settings(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
) -> list[SettingCategoryResponse]:
    """获取全部分组配置。

    返回按 category 分组的配置列表，llm.api_key 仅显示首尾 4 字符，避免敏感信息泄露。
    """
    return await service.get_all(user_id)


@router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_config(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
) -> LLMConfigResponse:
    """获取 LLM 配置。"""
    return await service.get_llm_config(user_id)


@router.put("/llm", response_model=LLMConfigResponse)
async def update_llm_config(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
    data: LLMConfigUpdate,
) -> LLMConfigResponse:
    """更新 LLM 配置。"""
    return await service.update_llm_config(user_id, data)


@router.get("/agent", response_model=AgentConfigResponse)
async def get_agent_config(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
) -> AgentConfigResponse:
    """获取 Agent 策略配置。"""
    return await service.get_agent_config(user_id)


@router.put("/agent", response_model=AgentConfigResponse)
async def update_agent_config(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
    data: AgentConfigUpdate,
) -> AgentConfigResponse:
    """更新 Agent 策略配置。"""
    return await service.update_agent_config(user_id, data)


@router.get("/job-rule", response_model=JobRuleConfigResponse)
async def get_job_rule_config(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
) -> JobRuleConfigResponse:
    """获取求职规则配置。"""
    return await service.get_job_rule_config(user_id)


@router.put("/job-rule", response_model=JobRuleConfigResponse)
async def update_job_rule_config(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
    data: JobRuleConfigUpdate,
) -> JobRuleConfigResponse:
    """更新求职规则配置。

    未配置项（None）即为 Approval 触发条件。
    """
    return await service.update_job_rule_config(user_id, data)


@router.get("/reply-style", response_model=ReplyStyleConfigResponse)
async def get_reply_style_config(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
) -> ReplyStyleConfigResponse:
    """获取回复风格配置。"""
    return await service.get_reply_style_config(user_id)


@router.put("/reply-style", response_model=ReplyStyleConfigResponse)
async def update_reply_style_config(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
    data: ReplyStyleConfigUpdate,
) -> ReplyStyleConfigResponse:
    """更新回复风格配置。"""
    return await service.update_reply_style_config(user_id, data)


@router.put("/batch")
async def batch_update_settings(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
    data: SettingBatchUpdate,
) -> dict:
    """批量更新配置。

    支持同时更新同一分类的多个配置项，事务保证原子性。
    """
    result = await service.batch_update(user_id, data.category, data)
    return {"status": "ok", "updated": len(result["updated_keys"])}


@router.post("/validate-llm")
async def validate_llm_settings(
    user_id: CurrentUserDep,
    service: SettingsServiceDep,
    data: LLMConfigUpdate | None = None,
) -> dict[str, Any]:
    """验证 LLM 配置连通性。

    优先用请求体里前端表单**当前填写**的 api_key（未落库也能测）；
    请求体未携带 api_key 时，回退读取已保存配置再探测。判定不依赖「先保存」。
    """
    if data is not None and data.api_key:
        ok, detail = await service.test_llm_connectivity(
            api_key=data.api_key,
            base_url=data.base_url,
            provider=data.provider,
        )
    else:
        from app.core.active_config_registry import get_active_config

        # 方案 A：优先读注册表中的活动配置（扩展已推送的明文 key）；为空回退 DB。
        current = get_active_config("llm")
        if not current.get("api_key"):
            current = await service.get_llm_runtime_config(user_id)
        ok, detail = await service.test_llm_connectivity(
            api_key=current.get("api_key"),
            base_url=current.get("base_url"),
            provider=current.get("provider"),
        )
    return {"ok": ok, "detail": detail}
