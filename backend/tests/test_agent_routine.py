"""例程注册表 + a11y 树解析/特征匹配测试（doc 17 预写例程框架）。"""

from __future__ import annotations

from app.agent.tools.routine import (
    Routine,
    RoutineRegistry,
    RoutineStep,
    TargetSpec,
    decode_tree_text,
    match_candidates,
    match_target,
    parse_tree,
)

# read_page 返回的 double-encoded 文本（mcp-server JSON.stringify 后的样子）
DOUBLE_ENCODED_TREE = (
    '"Page: BOSS直聘\\nURL: https://www.zhipin.com/\\n\\n'
    '  [ref_1 button \\"发送\\"]\\n'
    '  [ref_2 textbox \\"请输入消息\\" type=text]\\n'
    '    [ref_3 link \\"下一页\\" href=https://www.zhipin.com/page2]\\n"'
)

# 普通（未编码）树文本
PLAIN_TREE = """Page: BOSS直聘
URL: https://www.zhipin.com/

  [ref_1 button "发送"]
  [ref_2 textbox "请输入消息" type=text]
    [ref_3 link "下一页" href=https://www.zhipin.com/page2]
"""


class TestDecodeTreeText:
    def test_double_encoded_decoded(self) -> None:
        assert decode_tree_text(DOUBLE_ENCODED_TREE) == PLAIN_TREE

    def test_plain_passthrough(self) -> None:
        assert decode_tree_text(PLAIN_TREE) == PLAIN_TREE

    def test_non_json_string_passthrough(self) -> None:
        assert decode_tree_text("not a tree") == "not a tree"


class TestParseTree:
    def test_parse_plain_tree(self) -> None:
        nodes = parse_tree(PLAIN_TREE)
        assert [n.ref for n in nodes] == ["ref_1", "ref_2", "ref_3"]
        assert nodes[0].role == "button"
        assert nodes[0].label == "发送"
        assert nodes[1].type == "text"
        assert nodes[2].href == "https://www.zhipin.com/page2"

    def test_parse_double_encoded_tree(self) -> None:
        nodes = parse_tree(DOUBLE_ENCODED_TREE)
        assert [n.ref for n in nodes] == ["ref_1", "ref_2", "ref_3"]

    def test_parse_error_text_returns_empty(self) -> None:
        assert parse_tree('{"error": "boom"}') == []

    def test_depth_parsed(self) -> None:
        nodes = parse_tree(PLAIN_TREE)
        assert nodes[0].depth == 1
        assert nodes[2].depth == 2


class TestMatchTarget:
    def test_label_exact(self) -> None:
        tree = parse_tree(PLAIN_TREE)
        assert match_target(tree, TargetSpec(role="button", label_exact="发送")) == "ref_1"

    def test_label_contains(self) -> None:
        tree = parse_tree(PLAIN_TREE)
        assert match_target(tree, TargetSpec(label_contains="消息")) == "ref_2"

    def test_type_filter(self) -> None:
        tree = parse_tree(PLAIN_TREE)
        assert match_target(tree, TargetSpec(role="textbox", type="text")) == "ref_2"

    def test_nth_positive(self) -> None:
        tree = parse_tree(PLAIN_TREE)
        # 只有 1 个 button；nth=0 命中，nth=1 越界
        assert match_target(tree, TargetSpec(role="button", nth=0)) == "ref_1"
        assert match_target(tree, TargetSpec(role="button", nth=1)) is None

    def test_nth_negative_last(self) -> None:
        multi = '  [ref_1 button "A"]\n  [ref_2 button "B"]'
        tree = parse_tree(multi)
        assert match_target(tree, TargetSpec(role="button", nth=-1)) == "ref_2"

    def test_no_match(self) -> None:
        tree = parse_tree(PLAIN_TREE)
        assert match_target(tree, TargetSpec(label_contains="不存在的")) is None

    def test_match_candidates_order(self) -> None:
        multi = '  [ref_1 button "A"]\n  [ref_2 button "B"]'
        tree = parse_tree(multi)
        assert match_candidates(tree, TargetSpec(role="button")) == ["ref_1", "ref_2"]


class TestRoutineRegistry:
    def test_register_and_get(self) -> None:
        registry = RoutineRegistry()
        routine = Routine(
            id="chat.send_text",
            skill="browser.generic",
            steps=[
                RoutineStep(tool="chrome_fill_or_select", target=TargetSpec(role="textbox"), args={"value": "{text}"}),
                RoutineStep(tool="chrome_keyboard", args={"key": "Enter"}),
            ],
        )
        registry.register(routine)
        assert registry.get_by_skill("browser.generic") is routine
        assert registry.get_by_skill("boss.chat") is None
        assert registry.all == [routine]

    def test_register_overwrite(self) -> None:
        registry = RoutineRegistry()
        a = Routine(id="a", skill="s", steps=[])
        b = Routine(id="b", skill="s", steps=[])
        registry.register(a)
        registry.register(b)
        assert registry.get_by_skill("s") is b
        assert registry.all == [b]
