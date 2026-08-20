"""Planner Prompt 模板与 LLM 决策实现（doc 06 §5.3）。

设计：
- 不手写 JSON 解析：ChatOpenAI.with_structured_output(PlannerDecisionDTO)
  一次调用直接拿到 Pydantic 校验后的结构化决策（第三方库不重复造轮子）。
- LLM 配置由调用方（runtime）解析 Settings 后显式传入（含解密后的
  api_key）；planner 不读 DB，保持无状态、可独立测试。
- 所有 LLM 调用异常统一包装为 LLMPlanError，交给图编译期 RetryPolicy
  做瞬时重试（doc 06 §10），LangChain 客户端自身重试关闭避免双层重试。
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, SecretStr

from app.agent.graph.deps import LLMPlanError, PlannerContext, PlannerDecision

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt：垂直求职 Agent 的 ReAct 决策规约
# ---------------------------------------------------------------------------
PLANNER_SYSTEM_PROMPT = """你是求职自动化 Agent 的规划器（ReAct 模式）。

根据【会话历史】【当前计划】【最近观察】决定下一步动作，输出严格结构化决策。

next_action 取值（四选一）：
- skill_call：需要调用工具/Skill 完成 goal 描述的目标（如"提取当前页面岗位"）
- approval：目标涉及敏感操作（发送消息/打招呼等）且用户未配置授权
- sync：需要把累积的变更落库同步
- end：任务完成，无后续动作

决策纪律：
1. 观察驱动：skill_call 的结果会作为最近观察返回，据此再规划，不臆造结果
2. 敏感操作（发送类）未获用户明确配置时必须走 approval，不得直接 skill_call；
   approval_type 必须取七类敏感信息之一：salary/location/start_date/overtime/
   outsourcing/offsite/probation_salary（doc 14），其他值会被运行时拒绝
3. 计划 plan 输出完整计划（未完成步骤 status=pending，已完成 status=done）
4. goal 必须是具体可执行的目标描述，供 skill_router 映射到具体 Skill
"""

PLANNER_USER_TEMPLATE = """【任务类型】{task_type}
【会话历史】
{messages}
【当前计划】
{plan}
【当前步骤】第 {current_step} 步
【最近观察】
{recent_result}
【审批决策】{approval_decision}

请输出下一步决策。"""


@dataclass(frozen=True, slots=True)
class PlannerLLMConfig:
    """LLM 连接参数（runtime 从 Settings 解析并解密后注入）。"""

    model: str
    api_key: str
    base_url: str | None = None
    temperature: float = 0.7
    timeout: float = 30.0


class PlanStepDTO(BaseModel):
    """计划单步（LLM 结构化输出的最小单元）。"""

    step: int = Field(ge=1, description="步骤序号")
    goal: str = Field(description="该步目标")
    action: str = Field(description="该步动作（skill_call/sync/end 等）")
    status: Literal["pending", "done"] = "pending"


class PlannerDecisionDTO(BaseModel):
    """planner 结构化决策 schema（with_structured_output 的解析目标）。"""

    action: Literal["skill_call", "approval", "sync", "end"]
    goal: str | None = Field(None, description="skill_call/approval 时的目标描述")
    plan: list[PlanStepDTO] = Field(default_factory=list)
    needs_approval: bool = Field(False, description="是否触发人工确认")
    approval_type: str | None = Field(
        None,
        description="敏感信息类型，七选一：salary/location/start_date/overtime/outsourcing/offsite/probation_salary",
    )


def render_context(ctx: PlannerContext) -> str:
    """PlannerContext -> user 消息（纯函数，可独立单测）。

    截断策略：messages 只取最近 20 条、plan 只取 pending/done 摘要，控制
    token 预算（doc 06 §17 性能意识：planner 上下文是 token 大头）。
    """
    recent_msgs = ctx.messages[-20:]
    messages_text = "\n".join(f"- [{m.get('sender', 'unknown')}] {m.get('text', '')}" for m in recent_msgs) or "（无）"
    plan_text = (
        "\n".join(f"- {s.get('step', '?')}. {s.get('goal', '')} [{s.get('status', 'pending')}]" for s in ctx.plan)
        or "（空）"
    )
    recent = "（无）"
    if ctx.recent_result is not None:
        ok = ctx.recent_result.get("ok")
        data = ctx.recent_result.get("data") or {}
        err = ctx.recent_result.get("error")
        recent = f"ok={ok} data={data} error={err}"
    return PLANNER_USER_TEMPLATE.format(
        task_type=ctx.task_type,
        messages=messages_text,
        plan=plan_text,
        current_step=ctx.current_step,
        recent_result=recent,
        approval_decision=ctx.approval_decision or "（无）",
    )


class StructuredChatModel(Protocol):
    """可注入的聊天模型形状（生产 ChatOpenAI，测试用 Fake）。"""

    def with_structured_output(self, schema: type[BaseModel]) -> Any: ...  # noqa: ANN401


class LangchainPlanner:
    """PlannerLike 实现：LangChain 结构化输出 -> PlannerDecision。"""

    def __init__(self, config: PlannerLLMConfig, model: StructuredChatModel | None = None) -> None:
        self._config = config
        if model is None:
            # 局部导入：仅生产路径依赖 langchain-openai，测试注入 Fake 免依赖
            from langchain_openai import ChatOpenAI

            model = ChatOpenAI(
                model=config.model,
                api_key=SecretStr(config.api_key),
                base_url=config.base_url,
                temperature=config.temperature,
                timeout=config.timeout,
                max_retries=0,  # 重试交给图编译期 RetryPolicy，避免双层重试
            )
        self._structured = model.with_structured_output(PlannerDecisionDTO)

    async def plan(self, ctx: PlannerContext) -> PlannerDecision:
        """LLM 决策；失败统一抛 LLMPlanError（RetryPolicy 捕获重试）。"""
        prompt = render_context(ctx)
        try:
            dto = await self._structured.ainvoke([("system", PLANNER_SYSTEM_PROMPT), ("human", prompt)])
        except LLMPlanError:
            raise
        except Exception as exc:
            # 输出校验失败/网络/超时都属瞬时范畴，交给 RetryPolicy
            logger.warning("Planner LLM call failed", extra={"error": str(exc), "model": self._config.model})
            raise LLMPlanError(str(exc)) from exc
        if not isinstance(dto, PlannerDecisionDTO):
            # with_structured_output 返回类型异常（模型输出未过校验）
            msg = f"unexpected structured output type: {type(dto).__name__}"
            raise LLMPlanError(msg)
        return PlannerDecision(
            action=dto.action,
            goal=dto.goal,
            plan=[step.model_dump() for step in dto.plan],
            needs_approval=dto.needs_approval,
            approval_type=dto.approval_type,
        )
