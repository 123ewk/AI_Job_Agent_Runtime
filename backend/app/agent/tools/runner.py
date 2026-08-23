"""例程执行器（RoutineRunner，doc 17 确定性主路径）。

逐步骤执行：读 a11y 树 -> 特征匹配 ref -> 调 MCP 工具。树在例程开始时读
一次并跨步骤复用；发生页面变更（点击/输入/导航）后置为失效，下一目标步骤
重新读树。目标匹配失败先刷新一次树再重试（页面可能刚渲染完成）。
"""

from __future__ import annotations

from typing import Any, Protocol

from app.agent.tools.routine import Routine, match_target, parse_tree

# 会变更页面状态、使已读树失效的工具（下一步骤需重新读树）
_PAGE_MUTATORS = frozenset(
    {
        "chrome_click_element",
        "chrome_fill_or_select",
        "chrome_keyboard",
        "chrome_navigate",
        "chrome_handle_dialog",
    }
)


class AdapterToolResult(Protocol):
    """adapter 返回的标准化结果形状（BrowserToolAdapter.ToolResult 鸭子类型）。"""

    ok: bool
    data: dict[str, Any] | None
    error: str | None


class ToolCaller(Protocol):
    """可注入的工具调用器（BrowserToolAdapter / 测试 Fake 均满足）。"""

    async def call_tool(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> AdapterToolResult: ...


class RoutineError(Exception):
    """例程执行失败（缺目标/工具报错），由调用方决定重试或降级兜底。"""


def extract_tree_text(result: AdapterToolResult) -> str:
    """从 adapter 结果中取出树文本（data.text），非 str 时返回空串。"""
    data = result.data or {}
    text = data.get("text")
    return text if isinstance(text, str) else ""


class RoutineRunner:
    """逐步骤执行一条预写例程；成功返回最后一步结果，失败抛 RoutineError。"""

    def __init__(self, adapter: ToolCaller) -> None:
        self._adapter = adapter

    async def _read_tree(self) -> list[Any]:
        result = await self._adapter.call_tool("chrome_read_page", {})
        if not result.ok:
            msg = f"读取页面失败: {result.error}"
            raise RoutineError(msg)
        tree = parse_tree(extract_tree_text(result))
        if not tree:
            # 页面可能刚加载/渲染完成：刷新一次再读，仍空才算失败
            result = await self._adapter.call_tool("chrome_read_page", {})
            if not result.ok:
                msg = f"读取页面失败: {result.error}"
                raise RoutineError(msg)
            tree = parse_tree(extract_tree_text(result))
        if not tree:
            msg = "页面 a11y 树为空（可能不是可读页面）"
            raise RoutineError(msg)
        return tree

    async def run(self, routine: Routine, args: dict[str, Any]) -> AdapterToolResult:
        """执行例程。

        Raises:
            RoutineError: 任一步失败（缺目标/工具报错），消息含失败原因。
        """
        tree: list[Any] | None = None
        result: AdapterToolResult | None = None
        for step in routine.steps:
            # 步骤参数里的占位符 {key} 由调用方传入的 args 填充（如 {text}）
            call_args: dict[str, Any] = _resolve_placeholders(step.args, args)
            if step.target is not None:
                if tree is None:
                    tree = await self._read_tree()
                ref = match_target(tree, step.target)
                if ref is None:
                    msg = f"目标未找到: {step.target}"
                    raise RoutineError(msg)
                call_args["ref"] = ref
            result = await self._adapter.call_tool(step.tool, call_args)
            if not result.ok:
                msg = f"步骤 {step.tool} 失败: {result.error}"
                raise RoutineError(msg)
            if step.tool in _PAGE_MUTATORS:
                tree = None  # 页面已变，下一目标步骤重新读树
        if result is None:
            msg = f"例程 {routine.id} 为空（无步骤）"
            raise RoutineError(msg)
        return result


def _resolve_placeholders(step_args: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """用调用方 args 填充例程步骤参数（支持 {key} 模板）。

    例程步骤可写 {"value": "{text}"}，运行时取 args["text"] 替换；
    未命中的占位符原样保留（交给工具层校验）。
    """
    resolved: dict[str, Any] = {}
    for key, value in step_args.items():
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            inner = value[1:-1]
            if inner in args:
                resolved[key] = args[inner]
                continue
        resolved[key] = value
    return resolved
