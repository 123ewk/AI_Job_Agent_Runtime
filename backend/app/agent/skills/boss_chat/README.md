# boss_chat — Boss 直聘 HR 聊天页垂直工具

把「同步会话列表 → 拉取历史消息 → 预写并发送回复」封装为 future agent（doc 06）可直接编排的垂直领域工具。
浏览器结构依据 `docs/逆向网页分析/BOSS直聘_HR聊天页操作方案_V1.0.md`（下称「方案」）。**先落契约与实现，agent 运行时实现后接线**（见 SKILL.md「接线说明」）。

## 目录结构

```
backend/app/agent/skills/boss_chat/
├── __init__.py        # 包导出（BossChatService / ChatStoreLike / SkillResult）
├── SKILL.md           # doc 08 Skill 契约（目标/输入/输出/Prompt/Tool 需求/Recovery/接线）
├── chat-ops.js        # 浏览器操控脚本（MAIN world，注入用；list/messages/send 三操作分派）
├── service.py         # 编排：读（list/messages）→ 写（send）+ DOM 兜底（依赖注入，self-contained）
├── README.md
└── tests/
    ├── conftest.py    # sys.path 注入，支持独立 pytest
    └── test_service.py
```

## 数据流

```
浏览器(HR 聊天页, 已选中会话)
  ├── list    --chrome_javascript--> chat-ops.js(读 Vue $data.friendList)   -> Conversation[]
  │                                                └─ DOM 兜底(无 external_id)
  ├── message --chrome_javascript--> chat-ops.js(遍历 li.message-item)      -> Message[] + boss 元数据
  │                                                └─ DOM 兜底(有 data-mid/role)
  └── send    --chrome_javascript--> chat-ops.js(focus->预写->派发 Enter)    -> {dispatched,input_cleared,mine}
                                                （必须 approved=True，doc 14 审批）
```

- **零新增 zhipin 请求**（方案 §7）：list/messages 走已加载 Vue/DOM；不自动切换会话、不主动 WebSocket 重连。
- **写操作红**：send 必须 `approved=True`（方案 §7.3 + doc 14），service 侧拒绝未审批调用。
- **发简历（Q9）未实现**：方案 §8.2 标记流程未实测，需真实验证后再补 `send_resume`。

## 占位符注入（按键操控参数化）

`chat-ops.js` 顶部保留 `__OPERATION__` / `__PARAMS__`（两个 JSON 字面量），`service._build_script`
在注入前 `json.dumps` 替换。这样一份脚本承载三类操作，按键/文本参数安全转义，无 SQL/注入之虞。

## 独立运行测试

```bash
# 从仓库根（用 backend venv 跑）
backend/.venv/Scripts/python.exe -m pytest backend/app/agent/skills/boss_chat/tests -v

# 或进目录独立跑（conftest 自动注入 sys.path）
cd backend/app/agent/skills/boss_chat && python -m pytest tests -v
```

## 快速试跑（不连浏览器）

```python
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path("backend/app/agent/skills/boss_chat").resolve()))
from service import BossChatService


async def main():
    svc = BossChatService()  # 未接线：只读返回，不落库
    res = await svc.run(
        1,
        operation="list",
        raw_conversations=[
            {"external_id": "enc1", "hr_name": "黄先生", "position": "区域人事"},
        ],
    )
    print(res)
    # raw 路径：ok=True, source=raw，不触碰浏览器


asyncio.run(main())
```

## 接线路径（落地顺序）

1. `chrome_javascript` 从 `BROWSER_MCP_RISK_TOOLS` 净化（`backend/app/core/config.py`）+ 授权决策。
2. 注入：`BrowserToolAdapter` / `ChatStoreAdapter`（见 SKILL.md）。
3. doc 06 skill_router `map_goal_to_skill` 挂 `boss.chat`（list/messages/send 由 operation 分派）。
4. send 接入 doc 14 审批流（approved 来自审批决策）。方案 §7.3 写操作红线。
5. （后续）发简历 Q9 真实验证后补 `send_resume`。

## 设计要点（为什么这样写）

| 决定 | 理由 |
|---|---|
| 一份脚本 + `__OPERATION__`/`__PARAMS__` 占位符 | 注入端把脚本包成 `(function(){ code })()` 无参执行，用 JSON 字面量替换安全传参；三操作复用 |
| list 主走 Vue `$data.friendList` | external_id（`encryptBossId`）只在 Vue/API，DOM 没有（方案 §1.3）；零新增请求 |
| messages 走已加载 `li.message-item` | 零新增请求；role 由 item-friend/item-mine 判定（§2.6） |
| send 走页面原生 handleSend（方式 A） | 比手动模拟发送 API 稳，复用站点校验；成功判定按 §3.5 |
| send 必须 `approved=True` | 发送是真实对外行为（方案 §7.3 + doc 14），未审批拒绝 |
| external_id 不匹配不自动切换会话 | 切换=触发新 `historyMsg` 请求（§1.4），写路径交给真人/agent，防反检测 |
| 兜底 DOM 解析 external_id 置 None | 缺加密 ID 无法幂等落库，诚实标注 warning，不造假 |