"""预写例程注册表（doc 17：例程注册表 + RoutineFallback）。

例程 = 由稳定特征（role/label/type）描述的确定性浏览器操作序列，不硬编码
ref_*（页面刷新后失效）。执行时先读 a11y 树把特征解析成当前 ref，再逐步骤
调用 MCP 工具——这就是「常用操作预写、MCP 兜底」中的「预写」部分。

本轮只交付框架：注册表 API 就绪但为空，业务例程下一轮按需填充
（写操作 send 类不预写例程——走垂直服务 approved 红线；只读加载更多因 Boss 站
无限滚动+滚动即新请求，无安全只读实现，回退 browser.generic，见 builtin_routines）。

对齐红线：Skill/例程不写选择器；选择器由本模块的特征匹配持有（doc 07 §2）。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# a11y 树行：2 空格缩进 + [ref_1 role "label" type=text value="..."]
_TREE_LINE_RE = re.compile(r"^(\s*)\[(.*?)\]\s*$")
_TOKEN_RE = re.compile(r'("[^"]*")|(\S+)')

# 树解析防御上限：拒绝超长/畸形输出拖垮进程
_MAX_TREE_LINES = 4000

# 树行内布尔标记（accessibility-tree.js 输出 checked/disabled）
_BOOL_FLAGS = frozenset({"checked", "disabled"})


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """稳定元素特征（对齐 accessibility-tree.js 的行内字段）。

    全部为可选；组合后取交集。nth 用于同特征多元素（0=第一个，-1=最后一个）。
    """

    role: str | None = None
    label_contains: str | None = None
    label_exact: str | None = None
    type: str | None = None
    nth: int = 0


@dataclass(frozen=True, slots=True)
class RoutineStep:
    """例程单步：调哪个工具 + 作用于哪个目标 + 附加参数。"""

    tool: str
    target: TargetSpec | None = None
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Routine:
    """一条预写例程（确定性操作序列，不调 LLM）。"""

    id: str
    skill: str  # 绑定的 SkillCall.skill（如 browser.generic / boss.chat）
    steps: list[RoutineStep]
    retry: int = 2  # 整条例程重试次数（页面变化 ref 失效 → 重读树重新匹配）
    fallback: bool = True  # 重试耗尽后是否降级到兜底
    description: str = ""


@dataclass(frozen=True, slots=True)
class TreeNode:
    """a11y 树节点（行解析结果，供特征匹配）。"""

    ref: str
    depth: int
    role: str | None
    label: str
    type: str | None
    value: str | None
    checked: bool
    disabled: bool
    href: str | None
    raw: str


# ---------------------------------------------------------------------------
# a11y 树解析（read_page 返回文本 -> 节点列表）
# ---------------------------------------------------------------------------
def decode_tree_text(text: str) -> str:
    """解码 read_page 内容。

    mcp-server 对扩展返回做 JSON.stringify，content.text 是二次编码字符串
    （以 `"` 开头、`\n` 转义）；此处解码回原始树文本。非编码形式原样返回。
    """
    stripped = text.strip()
    if not stripped.startswith('"'):
        return text
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return text
    return decoded if isinstance(decoded, str) else text


def truncate_tree(text: str, max_chars: int = 6000) -> str:
    """按字符截断树文本（LLM 兜底喂 prompt 用，控制 token 预算）。"""
    out: list[str] = []
    total = 0
    for line in text.splitlines():
        if total + len(line) + 1 > max_chars:
            out.append(f"... (截断至 {max_chars} 字符)")
            break
        out.append(line)
        total += len(line) + 1
    return "\n".join(out)


def _parse_tokens(content: str) -> dict[str, Any]:
    """解析 [ref_1 button "发送" type=text value="..."] 为字段字典。"""
    tokens = [quoted or word for quoted, word in _TOKEN_RE.findall(content)]
    if not tokens:
        return {}
    fields: dict[str, Any] = {"ref": tokens[0]}
    for token in tokens[1:]:
        if token.startswith('"'):
            fields["label"] = token[1:-1]
        elif token in _BOOL_FLAGS:
            fields[token] = True
        elif "=" in token:
            key, _, val = token.partition("=")
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            fields[key] = val
        elif "role" not in fields:
            fields["role"] = token
        # 其他未知 token 忽略（保持解析器健壮）
    return fields


def parse_tree(text: str) -> list[TreeNode]:
    """解析 a11y 树文本为节点列表（文档顺序）。

    容忍 double-encoded 输入；非树文本（错误响应等）返回空列表。
    """
    decoded = decode_tree_text(text)
    nodes: list[TreeNode] = []
    for line_no, line in enumerate(decoded.splitlines()):
        if line_no >= _MAX_TREE_LINES:
            break
        match = _TREE_LINE_RE.match(line)
        if match is None:
            continue
        fields = _parse_tokens(match.group(2))
        ref = fields.get("ref")
        if not isinstance(ref, str):
            continue
        nodes.append(
            TreeNode(
                ref=ref,
                depth=len(match.group(1)) // 2,
                role=fields.get("role"),
                label=str(fields.get("label") or ""),
                type=fields.get("type"),
                value=fields.get("value"),
                checked=bool(fields.get("checked")),
                disabled=bool(fields.get("disabled")),
                href=fields.get("href"),
                raw=line,
            )
        )
    return nodes


# ---------------------------------------------------------------------------
# 特征匹配
# ---------------------------------------------------------------------------
def _node_matches(node: TreeNode, spec: TargetSpec) -> bool:
    if spec.role and (node.role or "").lower() != spec.role.lower():
        return False
    if spec.type and (node.type or "").lower() != spec.type.lower():
        return False
    label = node.label.strip()
    if spec.label_exact is not None and label.lower() != spec.label_exact.strip().lower():
        return False
    if spec.label_contains is not None:
        return spec.label_contains.lower() in label.lower()
    return True


def match_target(tree: list[TreeNode], spec: TargetSpec) -> str | None:
    """按特征返回匹配元素的 ref；nth<0 取最后一个，越界返回 None。"""
    matches = [n.ref for n in tree if _node_matches(n, spec)]
    if not matches:
        return None
    if spec.nth < 0:
        return matches[-1]
    if spec.nth < len(matches):
        return matches[spec.nth]
    return None


def match_candidates(tree: list[TreeNode], spec: TargetSpec) -> list[str]:
    """返回全部匹配 ref（文档顺序），供兜底逐候选尝试。"""
    return [n.ref for n in tree if _node_matches(n, spec)]


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
class RoutineRegistry:
    """例程注册表（进程内 dict，按 skill 索引；每 skill 至多一条）。"""

    def __init__(self) -> None:
        self._by_skill: dict[str, Routine] = {}

    def register(self, routine: Routine) -> None:
        """注册例程；同 skill 重复注册以新覆盖旧并告警。"""
        if routine.skill in self._by_skill:
            logger.warning(
                "routine_skill_overwritten",
                extra={"skill": routine.skill, "old": self._by_skill[routine.skill].id, "new": routine.id},
            )
        self._by_skill[routine.skill] = routine

    def get_by_skill(self, skill: str) -> Routine | None:
        """按 SkillCall.skill 取例程；未注册返回 None。"""
        return self._by_skill.get(skill)

    @property
    def all(self) -> list[Routine]:
        """已注册例程列表（诊断/审计用）。"""
        return list(self._by_skill.values())
