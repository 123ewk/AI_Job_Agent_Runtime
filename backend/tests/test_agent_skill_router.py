"""SkillExecutor 编排测试（doc 17：例程主路径 -> 重试 -> 双层兜底）。

不连 DB / 不连真实 MCP：FakeAdapter 脚本化 call_tool 返回，验证
例程命中、例程重试、兜底升级、fallback_mode 开关、浏览器锁。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.graph.deps import ERROR_KIND_DOM_CHANGE, ERROR_KIND_RULE_VIOLATION, SkillCall
from app.agent.runtime.lock_manager import LockManager
from app.agent.tools.fallback import FallbackDecision
from app.agent.tools.router import SkillExecutor
from app.agent.tools.routine import Routine, RoutineRegistry, RoutineStep, TargetSpec
from app.core.config import Settings, get_settings

TREE = (
    '"Page: BOSS\\nURL: https://www.zhipin.com/\\n\\n'
    '  [ref_1 textbox \\"输入框\\" type=text]\\n'
    '  [ref_2 button \\"发送\\"]\\n"'
)


@dataclass
class FakeResult:
    """BrowserToolAdapter.ToolResult 鸭子类型。"""

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class FakeAdapter:
    """脚本化 call_tool：按 (tool, args) 规则表返回结果，记录调用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        # 默认：read_page 返回树，其余工具成功
        self._tree = TREE
        self._fail_tools: set[str] = set()
        self._fail_n: dict[str, int] = {}

    def fail_tool(self, tool: str, *, times: int = 9999, error: str = "boom") -> None:
        """让某工具前 times 次调用失败（用于测试重试）。"""
        self._fail_tools.add(tool)
        self._fail_n[tool] = times
        self._fail_error = error

    async def call_tool(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,  # noqa: ARG002
    ) -> FakeResult:
        self.calls.append((name, args or {}))
        if name in self._fail_tools:
            remaining = self._fail_n.get(name, 0)
            if remaining > 0:
                self._fail_n[name] = remaining - 1
                return FakeResult(ok=False, error=getattr(self, "_fail_error", "boom"))
        if name == "chrome_read_page":
            return FakeResult(ok=True, data={"text": self._tree})
        return FakeResult(ok=True, data={"text": "ok"})


class FakeFallbackLLM:
    """脚本化兜底 LLM：按预设决策序列返回。"""

    def __init__(self, decisions: list[FallbackDecision] | None = None) -> None:
        self._decisions = list(decisions or [])
        self.calls: list[dict[str, Any]] = []

    async def decide(
        self,
        *,
        page_summary: str,
        goal: str,
        last_error: str | None,
    ) -> FallbackDecision:
        self.calls.append({"page_summary": page_summary, "goal": goal, "last_error": last_error})
        if self._decisions:
            return self._decisions.pop(0)
        return FallbackDecision(tool="chrome_read_page", args={}, done=True)


def make_settings(*, fallback_mode: str = "both") -> Settings:
    s = get_settings()
    s.browser_mcp_fallback_mode = fallback_mode
    return s


def make_executor(
    *,
    adapter: FakeAdapter,
    registry: RoutineRegistry | None = None,
    llm: FakeFallbackLLM | None = None,
    locks: LockManager | None = None,
    settings: Settings | None = None,
    chat_service: Any | None = None,  # noqa: ANN401 - duck-typed 垂直服务
    extract_service: Any | None = None,  # noqa: ANN401 - duck-typed 垂直服务
) -> SkillExecutor:
    return SkillExecutor(
        adapter=adapter,
        registry=registry,
        locks=locks or LockManager(),
        fallback_llm=llm,
        settings=settings or make_settings(),
        chat_service=chat_service,
        extract_service=extract_service,
    )


SEND_TEXT_ROUTINE = Routine(
    id="chat.send_text",
    skill="browser.generic",
    steps=[
        RoutineStep(tool="chrome_fill_or_select", target=TargetSpec(role="textbox"), args={"value": "{text}"}),
        RoutineStep(tool="chrome_keyboard", args={"key": "Enter"}),
    ],
)


class TestRoutineHit:
    async def test_routine_executes_steps(self) -> None:
        adapter = FakeAdapter()
        registry = RoutineRegistry()
        registry.register(SEND_TEXT_ROUTINE)
        executor = make_executor(adapter=adapter, registry=registry)

        result = await executor.execute(SkillCall(skill="browser.generic", args={"text": "你好"}, goal="发送消息"))

        assert result.ok is True
        tool_names = [name for name, _ in adapter.calls]
        # 首次目标步骤前读树 -> fill -> keyboard（fill 是页面变更工具，树失效但 keyboard 无目标不再读）
        assert tool_names == ["chrome_read_page", "chrome_fill_or_select", "chrome_keyboard"]
        fill_args = next(a for name, a in adapter.calls if name == "chrome_fill_or_select")
        assert fill_args["ref"] == "ref_1"
        assert fill_args["value"] == "你好"

    async def test_routine_target_not_found_retries_with_fresh_tree(self) -> None:
        adapter = FakeAdapter()

        class FlakyTreeAdapter(FakeAdapter):
            def __init__(self) -> None:
                super().__init__()
                self._reads = 0

            async def call_tool(
                self,
                name: str,
                args: dict[str, Any] | None = None,
                *,
                timeout: float | None = None,  # noqa: ARG002
            ) -> FakeResult:
                if name == "chrome_read_page":
                    self._reads += 1
                    # 第一次返回空树，第二次返回正常树（模拟页面延迟渲染）
                    if self._reads == 1:
                        return FakeResult(ok=True, data={"text": '"Page: x\\nURL: y\\n"'})
                return await super().call_tool(name, args)

        adapter = FlakyTreeAdapter()
        registry = RoutineRegistry()
        registry.register(SEND_TEXT_ROUTINE)
        executor = make_executor(adapter=adapter, registry=registry)

        result = await executor.execute(SkillCall(skill="browser.generic", args={"text": "hi"}, goal="发送"))

        assert result.ok is True
        # 第一次读树为空 -> runner 内刷新一次再读（首读 + 刷新 = 2 次）
        assert adapter._reads == 2
        fill_args = next(a for name, a in adapter.calls if name == "chrome_fill_or_select")
        assert fill_args["ref"] == "ref_1"


class TestRoutineRetryAndFallback:
    async def test_routine_retries_then_succeeds(self) -> None:
        adapter = FakeAdapter()
        adapter.fail_tool("chrome_fill_or_select", times=1)
        registry = RoutineRegistry()
        registry.register(SEND_TEXT_ROUTINE)
        executor = make_executor(adapter=adapter, registry=registry)

        result = await executor.execute(SkillCall(skill="browser.generic", args={"text": "hi"}, goal="发送"))

        assert result.ok is True
        # 例程 retry=2：第一次整条例程失败，第二次成功
        fill_calls = [a for name, a in adapter.calls if name == "chrome_fill_or_select"]
        assert len(fill_calls) == 2

    async def test_routine_retries_exhausted_then_adaptive_fallback_read(self) -> None:
        adapter = FakeAdapter()
        adapter.fail_tool("chrome_fill_or_select", times=9999)
        registry = RoutineRegistry()
        registry.register(SEND_TEXT_ROUTINE)
        # 无 LLM -> both 模式自动降级为 adaptive
        executor = make_executor(adapter=adapter, registry=registry, llm=None)

        result = await executor.execute(SkillCall(skill="browser.generic", args={"text": "hi"}, goal="发送"))

        # 例程失败重试耗尽 -> adaptive 兜底（goal 含"发送"，写操作不自动执行 -> None）
        # -> 无 LLM -> 最终失败（dom_change 可恢复）
        assert result.ok is False
        assert result.error_kind == ERROR_KIND_DOM_CHANGE

    async def test_routine_fallback_disabled_returns_error(self) -> None:
        adapter = FakeAdapter()
        adapter.fail_tool("chrome_fill_or_select", times=9999)
        registry = RoutineRegistry()
        registry.register(
            Routine(
                id="no_fallback",
                skill="browser.generic",
                steps=SEND_TEXT_ROUTINE.steps,
                fallback=False,
            )
        )
        executor = make_executor(adapter=adapter, registry=registry)

        result = await executor.execute(SkillCall(skill="browser.generic", args={"text": "hi"}, goal="发送"))

        assert result.ok is False
        assert "不允许兜底" in (result.error or "")


class TestNoRoutineFallback:
    async def test_no_routine_adaptive_read_returns_tree(self) -> None:
        adapter = FakeAdapter()
        executor = make_executor(adapter=adapter, llm=None)  # 空注册表

        result = await executor.execute(
            SkillCall(skill="browser.generic", args={"goal": "读取当前页面"}, goal="读取当前页面")
        )

        # adaptive：读取类目标 -> 返回树
        assert result.ok is True
        assert result.data == {"text": TREE}

    async def test_no_routine_llm_fallback_used(self) -> None:
        adapter = FakeAdapter()
        llm = FakeFallbackLLM(
            [
                FallbackDecision(tool="chrome_click_element", args={"ref": "ref_2"}, done=False),
                FallbackDecision(tool="chrome_read_page", args={}, done=True),
            ]
        )
        executor = make_executor(adapter=adapter, llm=llm)

        # 良性目标（无写操作词，adaptive 无法匹配 -> 升级 LLM）验证 LLM 兜底机制确实会触发
        result = await executor.execute(
            SkillCall(skill="browser.generic", args={"goal": "了解这个页面"}, goal="了解这个页面")
        )

        assert result.ok is True
        assert llm.calls, "LLM 兜底应被调用"
        tool_names = [name for name, _ in adapter.calls]
        assert "chrome_click_element" in tool_names

    async def test_llm_fallback_hard_blocks_send_goal(self) -> None:
        """LLM 兜底代码层硬拦写操作：goal 含发送词直接返回 None，不进 ReAct、不调用 LLM。"""
        from app.agent.tools.fallback import LLMFallback

        adapter = FakeAdapter()
        llm = FakeFallbackLLM()
        fb = LLMFallback(adapter, llm, max_steps=3, settings=make_settings())

        # 直接调 LLMFallback.run：绕过 adaptive，专门验证本层硬拦
        result = await fb.run("给 HR 发送消息")

        assert result is None
        assert llm.calls == []  # 未进入 ReAct，未调用 LLM

    async def test_llm_fallback_benign_goal_still_runs(self) -> None:
        """非写操作目标不受影响：LLM 兜底照常进入 ReAct。"""
        from app.agent.tools.fallback import LLMFallback

        adapter = FakeAdapter()
        llm = FakeFallbackLLM()
        fb = LLMFallback(adapter, llm, max_steps=3, settings=make_settings())

        result = await fb.run("了解这个页面")

        assert result is not None
        assert llm.calls, "良性目标应触发 LLM decide"

    async def test_fallback_mode_off_returns_error(self) -> None:
        adapter = FakeAdapter()
        executor = make_executor(adapter=adapter, settings=make_settings(fallback_mode="off"))

        result = await executor.execute(SkillCall(skill="browser.generic", args={"goal": "点击发送"}, goal="点击发送"))

        assert result.ok is False
        assert "兜底已关闭" in (result.error or "")


class TestEdgeCases:
    async def test_no_adapter_returns_rule_violation(self) -> None:
        executor = SkillExecutor(adapter=None, locks=LockManager())

        result = await executor.execute(SkillCall(skill="browser.generic", args={"goal": "读取"}, goal="读取"))

        assert result.ok is False
        assert result.error_kind == ERROR_KIND_RULE_VIOLATION
        assert "浏览器桥未启用" in (result.error or "")

    async def test_browser_lock_held_around_calls(self) -> None:
        adapter = FakeAdapter()
        locks = LockManager()

        acquired_during: list[bool] = []

        class RecordingAdapter(FakeAdapter):
            async def call_tool(
                self,
                name: str,
                args: dict[str, Any] | None = None,
                *,
                timeout: float | None = None,  # noqa: ARG002
            ) -> FakeResult:
                acquired_during.append(locks._browser_lock.locked())
                return await super().call_tool(name, args)

        adapter = RecordingAdapter()
        executor = make_executor(adapter=adapter, locks=locks)
        await executor.execute(SkillCall(skill="browser.generic", args={"goal": "读取当前页面"}, goal="读取当前页面"))

        assert acquired_during and all(acquired_during), "工具调用期间浏览器锁应被持有"

    async def test_map_goal_to_skill_returns_generic(self) -> None:
        executor = make_executor(adapter=FakeAdapter())
        call = executor.map_goal_to_skill("读取当前页面")
        assert call.skill == "browser.generic"
        assert call.goal == "读取当前页面"


@dataclass
class FakeSkillResult:
    """垂直服务 SkillResult{ok,data,error} 鸭子类型。"""

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class FakeChatService:
    """BossChatService 鸭子类型：记录调用；send 未审批按服务红线拒绝。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        *,
        user_id: int,
        operation: str,
        approved: bool = False,
        text: str | None = None,
        external_id: str | None = None,
        **_: Any,  # noqa: ANN401 - 透传会话/消息 raw 数据
    ) -> FakeSkillResult:
        self.calls.append(
            {"user_id": user_id, "operation": operation, "approved": approved, "text": text, "external_id": external_id}
        )
        if operation == "send" and not approved:
            return FakeSkillResult(ok=False, error="发送属高危写操作：approved 必须为 True（先走 doc 14 审批流）")
        return FakeSkillResult(ok=True, data={"operation": operation})


class FakeExtractService:
    """BossExtractService 鸭子类型：记录调用，成功返回。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, *, user_id: int, source: str = "page", **_: Any) -> FakeSkillResult:  # noqa: ANN401 - 透传 raw
        self.calls.append({"user_id": user_id, "source": source})
        return FakeSkillResult(ok=True, data={"source": source})


class TestMapGoalToSkillKeywords:
    async def test_extract_keywords_map_to_extract(self) -> None:
        executor = make_executor(adapter=FakeAdapter())
        for goal in ("提取岗位", "搜索职位", "抓取岗位", "拉取职位"):
            call = executor.map_goal_to_skill(goal)
            assert call.skill == "boss.extract_jobs", goal

    async def test_chat_keywords_map_to_chat(self) -> None:
        executor = make_executor(adapter=FakeAdapter())
        for goal in ("发送消息", "发消息", "回复", "拉取消息", "同步会话"):
            call = executor.map_goal_to_skill(goal)
            assert call.skill == "boss.chat", goal

    async def test_load_more_keywords_fall_back_to_generic(self) -> None:
        """加载更多/翻页/滚动：Boss 无限滚动无翻页按钮且滚动即新请求（非只读）→ 回退 generic。"""
        executor = make_executor(adapter=FakeAdapter())
        for goal in ("加载更多", "翻页", "下一页", "滚动"):
            call = executor.map_goal_to_skill(goal)
            assert call.skill == "browser.generic", goal

    async def test_generic_goal_stays_generic(self) -> None:
        executor = make_executor(adapter=FakeAdapter())
        for goal in ("读取当前页面", "分析页面内容"):
            assert executor.map_goal_to_skill(goal).skill == "browser.generic", goal


class TestVerticalDispatchChat:
    async def test_send_without_approval_is_rule_violation(self) -> None:
        adapter = FakeAdapter()
        chat = FakeChatService()
        executor = make_executor(adapter=adapter, chat_service=chat)

        result = await executor.execute(
            SkillCall(skill="boss.chat", args={"text": "你好"}, goal="发送消息")
        )

        assert result.ok is False
        assert result.error_kind == ERROR_KIND_RULE_VIOLATION
        assert "approved" in (result.error or "")
        # 派发层不新增自动审批：service 收到的 approved 为 False
        assert chat.calls[0]["operation"] == "send"
        assert chat.calls[0]["approved"] is False
        # dispatch 命中，不触碰浏览器工具 / 兜底
        assert adapter.calls == []

    async def test_messages_goal_is_read_only_success(self) -> None:
        chat = FakeChatService()
        executor = make_executor(adapter=FakeAdapter(), chat_service=chat)

        result = await executor.execute(SkillCall(skill="boss.chat", args={}, goal="拉取消息"))

        assert result.ok is True
        assert chat.calls[0]["operation"] == "messages"
        assert result.data == {"operation": "messages"}

    async def test_send_with_approval_and_text_allowed(self) -> None:
        chat = FakeChatService()
        executor = make_executor(adapter=FakeAdapter(), chat_service=chat)

        result = await executor.execute(
            SkillCall(skill="boss.chat", args={"text": "你好，方便聊聊吗", "approved": True}, goal="发送消息")
        )

        assert result.ok is True
        assert chat.calls[0]["operation"] == "send"
        assert chat.calls[0]["approved"] is True
        assert chat.calls[0]["text"] == "你好，方便聊聊吗"

    async def test_explicit_operation_takes_precedence(self) -> None:
        chat = FakeChatService()
        executor = make_executor(adapter=FakeAdapter(), chat_service=chat)

        await executor.execute(
            SkillCall(skill="boss.chat", args={"operation": "list"}, goal="发送消息")
        )

        assert chat.calls[0]["operation"] == "list"


class TestVerticalDispatchExtract:
    async def test_extract_dispatched_to_service(self) -> None:
        extract = FakeExtractService()
        executor = make_executor(adapter=FakeAdapter(), extract_service=extract)

        result = await executor.execute(SkillCall(skill="boss.extract_jobs", args={}, goal="提取岗位"))

        assert result.ok is True
        assert extract.calls[0]["user_id"] == 1
        assert extract.calls[0]["source"] == "page"


class TestUnwiredVerticalServices:
    async def test_chat_without_service_is_rule_violation(self) -> None:
        executor = make_executor(adapter=FakeAdapter())  # 无 chat_service

        result = await executor.execute(SkillCall(skill="boss.chat", args={}, goal="发送消息"))

        assert result.ok is False
        assert result.error_kind == ERROR_KIND_RULE_VIOLATION
        assert "垂直服务未接线" in (result.error or "")

    async def test_extract_without_service_is_rule_violation(self) -> None:
        executor = make_executor(adapter=FakeAdapter())  # 无 extract_service

        result = await executor.execute(SkillCall(skill="boss.extract_jobs", args={}, goal="提取岗位"))

        assert result.ok is False
        assert result.error_kind == ERROR_KIND_RULE_VIOLATION
        assert "垂直服务未接线" in (result.error or "")


class TestBuiltinReadonlyRoutine:
    def test_default_registry_has_no_routines(self) -> None:
        """默认内置例程当前为空：Boss「加载更多」无安全只读实现，故不注册任何假例程。"""
        executor = make_executor(adapter=FakeAdapter())  # 不注入 registry -> 默认注册内置例程
        assert executor._registry.get_by_skill("browser.load_more") is None
