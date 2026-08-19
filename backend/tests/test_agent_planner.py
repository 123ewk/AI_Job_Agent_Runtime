"""prompts/planner.py 单测：Fake 模型注入，不连真实 LLM。"""

import pytest

from app.agent.graph.deps import LLMPlanError, PlannerContext
from app.agent.prompts.planner import LangchainPlanner, PlannerDecisionDTO, render_context


class FakeStructured:
    """伪造 with_structured_output 链路：脚本化返回或抛错。"""

    def __init__(self, result: object | Exception) -> None:
        self._result = result
        self.invoked: list[tuple[str, str]] = []

    async def ainvoke(self, messages: list[tuple[str, str]]) -> object:
        self.invoked = messages  # type: ignore[assignment]
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeModel:
    def __init__(self, structured: FakeStructured) -> None:
        self._structured = structured

    def with_structured_output(self, schema: type) -> FakeStructured:
        assert schema is PlannerDecisionDTO
        return self._structured


def _make_planner(result: object | Exception) -> LangchainPlanner:
    from app.agent.prompts.planner import PlannerLLMConfig

    return LangchainPlanner(
        config=PlannerLLMConfig(model="test-model", api_key="sk-test"),  # 测试注入 Fake，config 不触网
        model=FakeModel(FakeStructured(result)),
    )


def _ctx() -> PlannerContext:
    return PlannerContext(
        task_type="proactive_job",
        messages=[{"sender": "hr", "text": "你好，我们岗位在招"}],
        plan=[{"step": 1, "goal": "提取岗位", "status": "done"}],
        current_step=2,
        recent_result={"ok": True, "data": {"created": 3}, "error": None},
        approval_decision=None,
    )


class TestRenderContext:
    def test_renders_all_sections(self) -> None:
        text = render_context(_ctx())
        assert "proactive_job" in text
        assert "你好，我们岗位在招" in text
        assert "提取岗位" in text
        assert "created" in text or "3" in text
        assert "（无）" in text  # approval_decision 为空

    def test_empty_context_uses_placeholders(self) -> None:
        text = render_context(PlannerContext(task_type="sync"))
        assert "（无）" in text
        assert "（空）" in text


class TestPlan:
    async def test_structured_decision_mapped(self) -> None:
        dto = PlannerDecisionDTO(action="skill_call", goal="提取岗位", plan=[])
        decision = await _make_planner(dto).plan(_ctx())
        assert decision.action == "skill_call"
        assert decision.goal == "提取岗位"
        assert decision.needs_approval is False

    async def test_llm_failure_wrapped_as_llm_plan_error(self) -> None:
        planner = _make_planner(TimeoutError("upstream timeout"))
        with pytest.raises(LLMPlanError):
            await planner.plan(_ctx())

    async def test_non_dto_output_rejected(self) -> None:
        planner = _make_planner({"action": "end"})  # 未过 Pydantic 校验的裸 dict
        with pytest.raises(LLMPlanError):
            await planner.plan(_ctx())
