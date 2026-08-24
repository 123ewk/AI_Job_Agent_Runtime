"""垂直工具 boss.chat 的编排服务：HR 聊天页 会话同步 / 消息拉取 / 回复发送。

设计（对齐 doc 08 Boss Skill 契约 + 逆向方案 BOSS直聘_HR聊天页操作方案_V1.0.md）：
- 自包含：与 backend/ 解耦（本文件不 import backend 任何模块），依赖全部经构造参数注入。
- 三类操作（operation）：
  - list：拉取当前已加载会话列表。主路径 chrome_javascript 注入 chat-ops.js 读 Vue
    $data.friendList（零新增请求，external_id=encryptBossId，方案 §1.3）；失败降级
    chrome_get_web_content DOM 兜底（external_id 缺失，写 warning）。
  - messages：拉取当前选中会话的已加载聊天记录（走 li.message-item，零新增请求）。
  - send：预写 + 派发 Enter 发送（方案 §3.5 方式 A）。**写操作，必须 approved=True**，
    未审批一律拒绝（方案 §7.3 + doc 14）。
- 兜底 DOM 解析用正则（best-effort，无浏览器授权风险）。
- 落库：注入 store（ChatStoreLike）幂等写 Conversation/Message；未注入则只读返回。

返回：SkillResult{ok, data, error}，data 随操作而异（见 SKILL.md）。

接线点（未来 doc 06 skill_router / tool_executor 注入）：
- adapter：注入 backend BrowserToolAdapter（call_tool 含浏览器锁/超时/域名白名单/审计）
- store：注入 backend ConversationService/MessageService 的薄封装 ChatStoreAdapter
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("boss_chat")

PLATFORM = "boss"
SCRIPT_PATH = Path(__file__).with_name("chat-ops.js")
_VALID_OPERATIONS = frozenset({"list", "messages", "send"})

# chrome_get_web_content 兜底：friend-content 会话项 / message-item 消息项
_RE_FRIEND_ITEM = re.compile(
    r'<div[^>]*class="[^"]*friend-content[^"]*"[^>]*>(?P<block>.*?)</div>', re.IGNORECASE | re.DOTALL
)
_RE_MSG_ITEM = re.compile(
    r'<li[^>]*class="[^"]*message-item[^"]*"[^>]*data-mid="(?P<mid>[^"]*)"[^>]*>(?P<block>.*?)</li>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


@dataclass
class SkillResult:
    """垂直工具统一返回（对齐 doc 08 SkillResult{ok, data, error}）。"""

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class ChatStoreLike(Protocol):
    """store 注入契约（duck-typing）。

    实际注入对象不必继承本类，只需实现两个方法；接线时由集成层把 backend 的
    ConversationService/MessageService 包成该形状（内部做 external_id / external_msg_id 幂等）。
    """

    async def upsert_conversation(self, user_id: int, conv: dict[str, Any]) -> object: ...

    async def append_messages(self, user_id: int, conversation_id: int, msgs: list[dict[str, Any]]) -> list[Any]: ...


# ---------------------------------------------------------------------------
# DOM 兜底解析（chrome_get_web_content 返回 {title, url, text, html}）
# ---------------------------------------------------------------------------
def _clean(raw: str | None) -> str | None:
    if not raw:
        return None
    t = _TAG_RE.sub("", raw)
    t = _SPACE_RE.sub(" ", t).strip()
    return t or None


def _text_by_class(html: str, cls: str) -> str | None:
    """取 html 内 class 含 cls 的首个元素文本（best-effort）。"""
    pat = r'<span[^>]*class="[^"]*' + re.escape(cls) + r'[^"]*"[^>]*>(.*?)</span>'
    m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
    return _clean(m.group(1)) if m else None


def _parse_conversations_html(html: str) -> list[dict[str, Any]]:
    """从 outerHTML 解析 .friend-content 会话项。best-effort，external_id 恒 None（DOM 无）。"""
    convs: list[dict[str, Any]] = []
    for m in _RE_FRIEND_ITEM.finditer(html or ""):
        block = m.group("block")
        convs.append(
            {
                "external_id": None,
                "unique_id": None,
                "friend_id": None,
                "encrypt_job_id": None,
                "hr_name": _text_by_class(block, "name-text"),
                "company": None,
                "position": None,
                "last_msg": _text_by_class(block, "last-msg-text"),
                "last_time": _text_by_class(block, "time"),
            }
        )
    return convs


def _parse_messages_html(html: str) -> list[dict[str, Any]]:
    """从 outerHTML 解析 li.message-item。role 由 li 的 class item-mine/item-friend 判定。

    注意：role 类在 <li> 开标签属性上，不在 block 内，故用整个匹配 match.group(0) 判断。
    """
    msgs: list[dict[str, Any]] = []
    for m in _RE_MSG_ITEM.finditer(html or ""):
        block = m.group("block")
        role = "user" if re.search(r'class="[^"]*item-mine[^"]*"', m.group(0)) else "hr"
        msgs.append(
            {
                "external_msg_id": m.group("mid") or None,
                "role": role,
                "content": _text_by_class(block, "text-content"),
                "sent_at": _text_by_class(block, "time"),
            }
        )
    return msgs


class BossChatService:
    """Boss HR 聊天页操作编排。依赖全部注入；store/adapter 为 None = 未接线（仍可 raw 输入）。"""

    def __init__(
        self,
        *,
        adapter: object | None = None,
        store: ChatStoreLike | None = None,
        script_path: str | Path | None = None,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.script_path = Path(script_path) if script_path else SCRIPT_PATH

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    async def run(
        self,
        user_id: int,
        *,
        operation: str,
        approved: bool = False,
        text: str | None = None,
        external_id: str | None = None,
        raw_conversations: list[dict[str, Any]] | None = None,
        raw_messages: list[dict[str, Any]] | None = None,
    ) -> SkillResult:
        """执行一次 HR 聊天操作。

        :param operation: "list" | "messages" | "send"
        :param approved: send 必须 True（doc 14 审批通过）才发送
        :param text: send 必填，预写并发送的回复文本
        :param external_id: 期望会话 encryptBossId（messages/send 时与当前会话校验）
        :param raw_conversations / raw_messages: 无浏览器时直接注入已读数据（只读场景）
        """
        if operation not in _VALID_OPERATIONS:
            return SkillResult(ok=False, error=f"未知 operation: {operation!r}（合法: list/messages/send）")

        try:
            if operation == "list":
                return await self._op_list(user_id, raw_conversations or [])
            if operation == "messages":
                return await self._op_messages(user_id, external_id, raw_messages or [])
            return await self._op_send(user_id, approved, text or "", external_id)
        except Exception as exc:
            logger.exception("boss_chat_run_failed", extra={"user_id": user_id, "operation": operation})
            return SkillResult(ok=False, error=str(exc))

    # ------------------------------------------------------------------
    # list
    # ------------------------------------------------------------------
    async def _op_list(self, user_id: int, raw: list[dict[str, Any]]) -> SkillResult:
        convs, warnings, source = await self._read_conversations(raw)
        if not convs:
            reason = warnings[0] if warnings else "未获取到会话列表"
            return SkillResult(
                ok=False,
                error=reason,
                data={"conversations": [], "warnings": warnings, "source": source},
            )
        ingested: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        # 仅 external_id 存在的会话可幂等落库（DOM 兜底 external_id=None 跳过落库）
        if self.store is not None:
            for conv in convs:
                if not conv.get("external_id"):
                    continue
                try:
                    created = await self.store.upsert_conversation(user_id, conv)
                    ingested.append(self._as_dict(created) or {"external_id": conv["external_id"]})
                except Exception as exc:
                    logger.warning(
                        "boss_chat_conv_persist_failed",
                        extra={"user_id": user_id, "external_id": conv.get("external_id"), "error": str(exc)},
                    )
                    errors.append({"external_id": conv.get("external_id"), "error": str(exc)})
        return SkillResult(
            ok=True,
            data={
                "conversations": convs,
                "source": source,
                "ingested": ingested,
                "errors": errors,
                "warnings": warnings,
            },
        )

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------
    async def _op_messages(self, user_id: int, external_id: str | None, raw: list[dict[str, Any]]) -> SkillResult:
        msgs, conv_meta, warnings = await self._read_messages(raw)
        if not msgs:
            reason = warnings[0] if warnings else "未获取到聊天记录"
            return SkillResult(
                ok=False,
                error=reason,
                data={"messages": [], "conversation": conv_meta, "warnings": warnings},
            )
        # 校验：调用方给期望会话 ID 时，须与当前选中会话一致（不自动切换，方案 §1.4）
        if external_id:
            current = (conv_meta or {}).get("external_id")
            if current is not None and current != external_id:
                return SkillResult(
                    ok=False,
                    error=(
                        f"当前选中会话 ({current}) 与期望会话 ({external_id}) 不一致；"
                        "本 Skill 不自动切换（切换会话=触发新 historyMsg 请求），请真人/agent 先切换"
                    ),
                    data={"messages": msgs, "conversation": conv_meta, "warnings": warnings},
                )

        ingested: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        # 落库前提：会话必须先存在（消息挂到 conversation_id 上）。
        # conv_meta 来自脚本（{external_id, hr_name, ...}），无 DB id → 先 upsert 会话取 id。
        conv_id: int | None = None
        if self.store is not None and conv_meta and conv_meta.get("external_id"):
            try:
                created = await self.store.upsert_conversation(user_id, self._conv_payload(conv_meta))
                conv_dict = self._as_dict(created) or {}
                conv_id = conv_dict.get("id")
            except Exception as exc:
                logger.warning(
                    "boss_chat_conv_persist_failed",
                    extra={"user_id": user_id, "external_id": conv_meta.get("external_id"), "error": str(exc)},
                )
                errors.append({"error": str(exc)})
        if self.store is not None and conv_id is not None:
            try:
                ingest_msgs = [m for m in msgs if m.get("external_msg_id") is not None]
                saved = await self.store.append_messages(user_id, conv_id, ingest_msgs)
                ingested = [
                    self._as_dict(x) or {"external_msg_id": m.get("external_msg_id")}
                    for m, x in zip(ingest_msgs, saved, strict=True)
                ]
            except Exception as exc:
                logger.warning("boss_chat_msg_persist_failed", extra={"user_id": user_id, "error": str(exc)})
                errors.append({"error": str(exc)})
        return SkillResult(
            ok=True,
            data={
                "messages": msgs,
                "conversation": conv_meta,
                "source": "dom",
                "ingested": ingested,
                "errors": errors,
                "warnings": warnings,
            },
        )

    # ------------------------------------------------------------------
    # send
    # ------------------------------------------------------------------
    async def _op_send(self, user_id: int, approved: bool, text: str, external_id: str | None) -> SkillResult:
        # 红线段锁：写操作必须经审批（方案 §7.3 + doc 14）
        if not approved:
            return SkillResult(ok=False, error="发送属高危写操作：approved 必须为 True（先走 doc 14 审批流）")
        if not text or not text.strip():
            return SkillResult(ok=False, error="发送文本为空")
        if self.adapter is None:
            return SkillResult(ok=False, error="浏览器适配器未接线（注入 adapter，或设置 BROWSER_MCP_ENABLED）")

        # 会话校验：期望 external_id 与当前选中会话须一致，避免「发给谁」错位（对齐 _op_messages §1.4）。
        # 复用只读 messages 的 conv_meta 取当前会话 id，零浏览器写副作用。
        if external_id:
            _, conv_meta, _ = await self._read_messages([])
            current = (conv_meta or {}).get("external_id")
            if current is not None and current != external_id:
                return SkillResult(
                    ok=False,
                    error=(
                        f"当前选中会话 ({current}) 与期望会话 ({external_id}) 不一致；"
                        "本 Skill 不自动切换（切换会话=触发新 historyMsg 请求），请真人/agent 先切换"
                    ),
                )

        result = await self.adapter.call_tool(
            "chrome_javascript", {"code": await self._build_script("send", {"text": text})}
        )
        if not result.ok:
            return SkillResult(ok=False, error=f"chrome_javascript 调用失败: {result.error}")
        data = result.data if isinstance(result.data, dict) else {}
        if data.get("ok") is not True:
            return SkillResult(ok=False, error=data.get("error") or "发送失败（脚本返回异常）", data=data)
        logger.info(
            "boss_chat_send_dispatched",
            extra={"user_id": user_id, "external_id": external_id, "input_cleared": data.get("input_cleared")},
        )
        return SkillResult(ok=True, data=data)

    # ------------------------------------------------------------------
    # 读取（脚本注入主路径 / DOM 兜底）
    # ------------------------------------------------------------------
    async def _read_conversations(
        self, raw: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str], str | None]:
        if raw:
            return list(raw), [], "raw"
        if self.adapter is None:
            return [], ["浏览器适配器未接线（注入 adapter，或设置 BROWSER_MCP_ENABLED）"], None

        result = await self.adapter.call_tool("chrome_javascript", {"code": await self._build_script("list", {})})
        if result.ok and isinstance(result.data, dict) and result.data.get("ok") is True:
            return (
                result.data.get("conversations") or [],
                list(result.data.get("warnings") or []),
                result.data.get("source") or "vue",
            )

        dom_convs, dom_warnings = await self._extract_conversations_from_dom()
        if dom_convs:
            return dom_convs, dom_warnings, "dom"
        return [], [result.error or "提取失败", *dom_warnings], None

    async def _read_messages(
        self, raw: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[str]]:
        if raw:
            return list(raw), None, []
        if self.adapter is None:
            return [], None, ["浏览器适配器未接线（注入 adapter，或设置 BROWSER_MCP_ENABLED）"]

        result = await self.adapter.call_tool("chrome_javascript", {"code": await self._build_script("messages", {})})
        if result.ok and isinstance(result.data, dict) and result.data.get("ok") is True:
            msgs = result.data.get("messages") or []
            conv = result.data.get("conversation") or None
            return msgs, conv, list(result.data.get("warnings") or [])

        dom_msgs, dom_warnings = await self._extract_messages_from_dom()
        if dom_msgs:
            return dom_msgs, None, dom_warnings
        return [], None, [result.error or "提取失败", *dom_warnings]

    async def _extract_conversations_from_dom(self) -> tuple[list[dict[str, Any]], list[str]]:
        result = await self.adapter.call_tool("chrome_get_web_content", {})
        if not result.ok:
            return [], [f"chrome_get_web_content 兜底失败: {result.error}"]
        data = result.data if isinstance(result.data, dict) else {}
        convs = _parse_conversations_html(data.get("html") or "") if data.get("html") else []
        if not convs:
            return [], ["DOM 兜底未解析出会话项"]
        return convs, ["DOM 兜底：external_id 缺失（需 Vue friendList），无法幂等落库"]

    async def _extract_messages_from_dom(self) -> tuple[list[dict[str, Any]], list[str]]:
        result = await self.adapter.call_tool("chrome_get_web_content", {})
        if not result.ok:
            return [], [f"chrome_get_web_content 兜底失败: {result.error}"]
        data = result.data if isinstance(result.data, dict) else {}
        msgs = _parse_messages_html(data.get("html") or "") if data.get("html") else []
        if not msgs:
            return [], ["DOM 兜底未解析出消息项"]
        return msgs, ["DOM 兜底：会话 external_id 缺失（需 Vue $data.boss）"]

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    async def _build_script(self, op: str, params: dict[str, Any]) -> str:
        """把 chat-ops.js 的 __OPERATION__/__PARAMS__ 占位符填成 JSON 字面量。

        ensure_ascii=False：保留中文/其他非 ASCII 字面量（json 仍转义引号/反斜杠/控制符，
        无注入风险）；否则 json.dumps 默认把 CJK 转义为 \\uXXXX，注入代码不可读、不符预期。
        """
        script = await asyncio.to_thread(self.script_path.read_text, encoding="utf-8")
        return script.replace("__OPERATION__", json.dumps(op, ensure_ascii=False)).replace(
            "__PARAMS__", json.dumps(params, ensure_ascii=False)
        )

    @staticmethod
    def _conv_payload(conv_meta: dict[str, Any]) -> dict[str, Any]:
        """把脚本返回的会话元数据裁剪成 upsert_conversation 载荷（只传落库必需字段，跳过 None）。

        目标字段对齐 backend ConversationCreate（external_id 是去重键，hr_name 展示）。
        job_id / job_title / hr_id 关联由集成层 ChatStoreAdapter 从 external_id 反查
        （本工具不臆造数字 job_id，也不把 HR 的 position 错当 job_title）。
        """
        out: dict[str, Any] = {}
        if conv_meta.get("external_id"):
            out["external_id"] = conv_meta["external_id"]
        if conv_meta.get("hr_name"):
            out["hr_name"] = conv_meta["hr_name"]
        return out

    @staticmethod
    def _as_dict(obj: object) -> dict[str, Any] | None:
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj
        data = getattr(obj, "model_dump", None) or getattr(obj, "dict", None)
        if callable(data):
            d = data()
            return d if isinstance(d, dict) else None
        return {"id": obj.id} if hasattr(obj, "id") else None
