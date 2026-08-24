"""BossChatService 单测：三类操作 + 授权闸门 + DOM 兜底 + 占位符注入。

不连浏览器/DB：adapter / store / 脚本注入全用 Fake。脚本注入脚本读真实 chat-ops.js，
断言 __OPERATION__/__PARAMS__ 被 json 字面量替换（验证「预写按键操控代码」参数化）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from service import BossChatService, SkillResult  # conftest 已注入 sys.path

# ---------------------------------------------------------------------------
# Fake adapter / store
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """脚本化浏览器 adapter：按注入脚本内容路由返回，记录调用。"""

    def __init__(self, script_result: dict[str, Any] | None = None) -> None:
        self.script_result = script_result or {"ok": False, "error": "no script stub"}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.dom_result: dict[str, Any] | None = None

    async def call_tool(self, name: str, args: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
        self.calls.append((name, args or {}))
        if name == "chrome_javascript":
            return SimpleNamespace(ok=True, data=dict(self.script_result), error=None)
        if name == "chrome_get_web_content":
            if self.dom_result is None:
                return SimpleNamespace(ok=False, data=None, error="no dom stub")
            return SimpleNamespace(ok=True, data=dict(self.dom_result), error=None)
        return SimpleNamespace(ok=False, data=None, error=f"unknown {name}")


class _FakeStore:
    def __init__(self) -> None:
        self.convs: list[dict[str, Any]] = []
        self.msgs: list[dict[str, Any]] = []

    async def upsert_conversation(self, user_id: int, conv: dict[str, Any]) -> object:  # noqa: ARG002
        self.convs.append(conv)
        return {"id": len(self.convs) + 100, "external_id": conv.get("external_id")}

    async def append_messages(self, user_id: int, conversation_id: int, msgs: list[dict[str, Any]]) -> list[Any]:  # noqa: ARG002
        self.msgs.extend(msgs)
        return [dict(m) for m in msgs]


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


async def test_list_vue_path_returns_conversations() -> None:
    """list：Vue 主路径返回会话（含 external_id）+ warning。"""
    adapter = _FakeAdapter(
        {
            "ok": True,
            "source": "vue",
            "conversations": [
                {
                    "external_id": "enc1",
                    "unique_id": "733519801-0",
                    "friend_id": 733519801,
                    "encrypt_job_id": "job1",
                    "hr_name": "黄先生",
                    "company": "江苏环益童心信息科技",
                    "position": "区域人事",
                    "last_msg": "同学有兴趣了一下吗",
                }
            ],
            "warnings": ["Vue friendList 的 company/position 字段为 best-effort 映射"],
        }
    )
    svc = BossChatService(adapter=adapter, store=_FakeStore())
    res: SkillResult = await svc.run(1, operation="list")

    assert res.ok
    assert res.data  # type: ignore[union-attr]
    assert res.data["conversations"][0]["external_id"] == "enc1"  # type: ignore[index]
    assert res.data["source"] == "vue"  # type: ignore[index]
    # 脚本参数已注入 json 字面量
    assert '"list"' in adapter.calls[0][1]["code"]


async def test_list_without_external_id_skips_persist() -> None:
    """list DOM 兜底：external_id=None 的会话不入 store。"""
    adapter = _FakeAdapter(
        {
            "ok": True,
            "source": "dom",
            "conversations": [{"external_id": None, "hr_name": "李女士", "position": "HR"}],
            "warnings": ["DOM 兜底：external_id 缺失"],
        }
    )
    store = _FakeStore()
    svc = BossChatService(adapter=adapter, store=store)
    res: SkillResult = await svc.run(1, operation="list")

    assert res.ok
    assert store.convs == []  # external_id None → 不落库


async def test_list_dom_fallback_from_content() -> None:
    """list：chrome_javascript 失败 → chrome_get_web_content DOM 兜底。"""
    adapter = _FakeAdapter({"ok": False, "error": "chrome_javascript 未授权"})
    adapter.dom_result = {
        "html": (
            '<div class="friend-content"><div class="title-box">'
            '<span class="name-text">王先生</span>'
            '</div><div class="gray last-msg"><span class="last-msg-text">你好</span></div>'
            '<div><span class="time">07月25日</span></div></div>'
        )
    }
    svc = BossChatService(adapter=adapter)
    res: SkillResult = await svc.run(1, operation="list")

    assert res.ok
    assert res.data["source"] == "dom"  # type: ignore[index]
    assert res.data["conversations"][0]["hr_name"] == "王先生"  # type: ignore[index]
    assert res.data["conversations"][0]["external_id"] is None  # type: ignore[index]
    assert res.data["warnings"]  # type: ignore[index]


async def test_list_no_adapter_raw_input() -> None:
    """list：无浏览器 → raw 注入直接返回，不落库不报错。"""
    svc = BossChatService()  # adapter=None
    res: SkillResult = await svc.run(1, operation="list", raw_conversations=[{"external_id": "encR"}])
    assert res.ok
    assert res.data["source"] == "raw"  # type: ignore[index]


async def test_list_invalid_operation() -> None:
    """超范围 operation 报错。"""
    svc = BossChatService()
    res: SkillResult = await svc.run(1, operation="hack")
    assert not res.ok


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------


async def test_messages_returns_and_persists() -> None:
    """messages：返回聊天记录 role 映射 + external_id 校验通过 + 落库。"""
    adapter = _FakeAdapter(
        {
            "ok": True,
            "source": "dom",
            "conversation": {
                "external_id": "encX",
                "hr_name": "陈经理",
                "encrypt_job_id": "jobX",
                "unique_id": "1-0",
                "friend_id": 1,
            },
            "messages": [
                {"external_msg_id": "1001", "role": "hr", "content": "在吗", "sent_at": "07-24 18:32"},
                {"external_msg_id": None, "role": "user", "content": "在的", "sent_at": "07-24 18:33"},
            ],
            "warnings": [],
        }
    )
    store = _FakeStore()
    svc = BossChatService(adapter=adapter, store=store)
    res: SkillResult = await svc.run(1, operation="messages", external_id="encX")

    assert res.ok
    msgs = res.data["messages"]  # type: ignore[index]
    assert msgs[0]["role"] == "hr"  # type: ignore[index]
    assert msgs[1]["role"] == "user"  # type: ignore[index]
    # 落库：仅 external_msg_id 存在的消息
    assert [m["external_msg_id"] for m in store.msgs] == ["1001"]
    assert res.data["conversation"]["external_id"] == "encX"  # type: ignore[index]


async def test_messages_external_id_mismatch_rejected() -> None:
    """messages：期望会话与当前会话不一致时拒绝，不自动切换。"""
    adapter = _FakeAdapter(
        {
            "ok": True,
            "source": "dom",
            "conversation": {"external_id": "currentA", "hr_name": "A"},
            "messages": [{"external_msg_id": "1", "role": "hr", "content": "hi", "sent_at": "t"}],
            "warnings": [],
        }
    )
    svc = BossChatService(adapter=adapter, store=_FakeStore())
    res: SkillResult = await svc.run(1, operation="messages", external_id="wantB")
    assert not res.ok
    assert "不自动切换" in (res.error or "")


async def test_messages_dom_fallback_parse() -> None:
    """messages：chrome_javascript 失败 → chrome_get_web_content DOM 兜底解析角色。"""
    adapter = _FakeAdapter({"ok": False, "error": "chart_javascript 被拒"})
    adapter.dom_result = {
        "html": (
            '<li class="message-item item-friend" data-mid="2001">'
            '<div><span class="time">07-25 09:01</span></div>'
            '<div class="text"><p><span class="text-content">你好呀</span></p></div></li>'
            '<li class="message-item item-mine" data-mid="2002">'
            '<div class="text"><p><span class="text-content">您好</span></p></div></li>'
        )
    }
    svc = BossChatService(adapter=adapter)
    res: SkillResult = await svc.run(1, operation="messages")
    assert res.ok
    msgs = res.data["messages"]  # type: ignore[index]
    assert [m["role"] for m in msgs] == ["hr", "user"]  # type: ignore[index]
    assert [m["external_msg_id"] for m in msgs] == ["2001", "2002"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# send（写操作授权闸门）
# ---------------------------------------------------------------------------


async def test_send_without_approval_refused() -> None:
    """send：未 approved 拒绝，不触碰 adapter。"""
    adapter = _FakeAdapter()
    svc = BossChatService(adapter=adapter)
    res: SkillResult = await svc.run(1, operation="send", text="你好")
    assert not res.ok
    assert "approved" in (res.error or "")
    assert adapter.calls == []  # 未调用浏览器


async def test_send_approved_dispatches_correct_text() -> None:
    """send：approved 后注入脚本，text 以 JSON 字面量嵌入。"""
    adapter = _FakeAdapter(
        {
            "ok": True,
            "dispatched": True,
            "input_cleared": True,
            "mine": {"external_msg_id": "3001", "content": "好的，我考虑一下"},
        }
    )
    svc = BossChatService(adapter=adapter)
    res: SkillResult = await svc.run(1, operation="send", approved=True, text="好的，我考虑一下")

    assert res.ok
    assert res.data["dispatched"] is True  # type: ignore[index]
    code = adapter.calls[0][1]["code"]
    assert '"send"' in code
    assert '"好的，我考虑一下"' in code  # 文本 JSON 转义嵌入


async def test_send_script_reports_failure() -> None:
    """send：脚本返回 ok=false（如按钮仍 disabled）→ 上抛 error。"""
    adapter = _FakeAdapter({"ok": False, "error": "输入事件未生效，发送按钮仍 disabled"})
    svc = BossChatService(adapter=adapter)
    res: SkillResult = await svc.run(1, operation="send", approved=True, text="x")
    assert not res.ok
    assert "disabled" in (res.error or "")


async def test_send_no_adapter() -> None:
    """send：adapter 未接线 → 拒绝。"""
    svc = BossChatService()
    res: SkillResult = await svc.run(1, operation="send", approved=True, text="x")
    assert not res.ok
    assert "适配器未接线" in (res.error or "")


async def test_send_empty_text_rejected() -> None:
    """send：空文本拒绝。"""
    svc = BossChatService(adapter=_FakeAdapter())
    res: SkillResult = await svc.run(1, operation="send", approved=True, text="   ")
    assert not res.ok


async def test_send_conversation_mismatch_refused() -> None:
    """send：期望 external_id 与当前选中会话不一致 → 拒绝，不真正发送。"""
    adapter = _FakeAdapter(
        {"ok": True, "conversation": {"external_id": "CURRENT"}, "messages": [], "warnings": []}
    )
    svc = BossChatService(adapter=adapter)
    res: SkillResult = await svc.run(
        1, operation="send", approved=True, text="你好", external_id="EXPECTED"
    )

    assert not res.ok
    assert "不一致" in (res.error or "")
    assert len(adapter.calls) == 1  # 只做了一次会话读取，未触发 send 脚本


async def test_send_conversation_match_dispatches() -> None:
    """send：期望 external_id 与当前会话一致 → 正常发送（前多一次只读会话读取）。"""
    adapter = _FakeAdapter(
        {"ok": True, "conversation": {"external_id": "EXPECTED"}, "messages": [], "warnings": []}
    )
    svc = BossChatService(adapter=adapter)
    res: SkillResult = await svc.run(
        1, operation="send", approved=True, text="你好", external_id="EXPECTED"
    )

    assert res.ok
    assert len(adapter.calls) == 2  # 1 次会话读取 + 1 次 send
