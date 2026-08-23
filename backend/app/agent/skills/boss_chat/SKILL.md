# Skill: boss.chat — Boss 直聘 HR 聊天页操作（会话同步 / 消息拉取 / 回复发送）

> 对齐 `docs/AI求职Agent_设计文档_V2.0/08-Boss Skill详细接口设计.md` 的 Goal-Oriented Skill 模板，
> 浏览器结构依据 `docs/逆向网页分析/BOSS直聘_HR聊天页操作方案_V1.0.md`（下称「方案」）。
> **垂直领域工具**：把「同步会话列表 → 拉取历史消息 → 预写并发送回复」封装为 agent 可直接编排的 Skill。
> 浏览器能力经项目通用 chrome-mcp-server 的 `chrome_*` 工具兜底（Tool Adapter 域名白名单 + 浏览器锁）。

---

## 目标（Goal）

在**真实浏览器已打开的 Boss 直聘 HR 聊天页**（`https://www.zhipin.com/web/geek/chat`，方案 §0）上，
执行下列任一操作（由 `operation` 指定），并严格遵循方案 §7 反检测红线：

- `list`：拉取**当前已加载**的会话列表（优先读页面内存 Vue `friendList`，**零新增 zhipin 请求**）。
- `messages`：拉取**当前选中会话**已加载的聊天记录（遍历 `li.message-item`，零新增请求）。
- `send`：向当前会话**预写并发送**回复文本（方案 §3.5 方式 A：focus → 预写 → 派发 Enter）。
  **写操作，必须 `approved=True` 才执行**（方案 §7.3 + doc 14 审批流）。

## 输入（Input）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `user_id` | int | 是 | 目标用户（单用户部署恒为 1，接线后由 agent 传入） |
| `operation` | str | 是 | `"list"` \| `"messages"` \| `"send"` |
| `approved` | bool | send 必填 | `True` 才执行发送；必须经 doc 14 审批流确认 |
| `text` | str | send 必填 | 预写到 `#chat-input` 并发送的回复文本 |
| `external_id` | str | 否 | 期望会话的 `encryptBossId`；`messages/send` 时与当前选中会话校验，不匹配则拒绝 |
| `raw_*` | 任意 | 否 | 无浏览器时的注入数据（见下） |
| `store` | ChatStoreLike | 否 | 未注入则只读返回，不落库 |

## 输出（Output）

```json
{ "ok": true, "data": { ... } }
```

各 `operation` 的 `data` 结构：
- **list**：`{ source:"vue"|"dom", conversations:[{external_id, unique_id, friend_id, encrypt_job_id, hr_name, company, position, last_msg, last_time}] }`
- **messages**：`{ source:"dom", conversation:{external_id, hr_name, encrypt_job_id, unique_id}, messages:[{external_msg_id, role:"hr"|"user", content, sent_at}] }`
- **send**：`{ dispatched:true, input_cleared:bool, mine:{external_msg_id, content}|null }`

> `ok=false` 时 `error` 携带具体阻断原因；`data.warnings` 记录 best-effort 偏差（不含外部 ID / 事件未生效等）。

## Prompt（指导 Agent 达成目标）

1. 前置：确认浏览器当前选中**HR 聊天会话**（`/web/geek/chat`），且已登录。
2. **只读**操作（list/messages）调用本 Skill，`operation` 对应；返回的 `role=hr` 消息若为待回复，转 planner 决策。
3. **发送**：先把回复文本交用户/审批流确认，**只有 `approved=True`** 才调 `operation=send`；成功后按方案 §3.5 二次 `messages` 复查状态流转（loading→delivery→read）。
4. 全程仅允许 `zhipin.com` 域（Tool Adapter 白名单兜底）；**不主动 WebSocket 重连**（方案 §7.4）。

## Tool 需求（浏览器能力类别）

| 能力 | 工具 | 用途 |
|---|---|---|
| 脚本注入（**操作主路径**） | `chrome_javascript` | 注入 `chat-ops.js`（读 Vue/DOM、预写+派发 Enter），参数经 `__OPERATION__`/`__PARAMS__` 注入 |
| 内容读取（**兜底**） | `chrome_get_web_content` | `chrome_javascript` 不可用时解析 DOM（best-effort，且仅列表/消息；external_id 从 Vue 取，DOM 无） |

> ✅ **授权状态（2026-08-23 已放行）**：`chrome_javascript` 已从 `BROWSER_MCP_RISK_TOOLS` 移除（净化，见 `backend/app/core/config.py` + `.env.example`），本 Skill 主路径可直接注入。
> 仍保留高危待授权：`chrome_network_request`（非只读、可签发任意流量）。
> 兜底语义保留：即使 `chrome_javascript` 被拒/报错，list/messages 仍降级 `chrome_get_web_content` DOM 兜底；send 无法注入 → 明确报错。

## 前置（DomainGuard 约束）

- 用户在真实 Chrome **当前选中**目标 HR 会话（方案 §1.4：切换会话 = 新 `historyMsg` 请求，属写路径，
  本 Skill **不自动切换**，由真人/agent 交互完成）。
- 会话 `external_id`（`encryptBossId`）需从 Vue `friendList` / `$data.boss` 获取；**DOM 没有**（方案 §1.3）。
- send 需 `approved=True`（doc 14 审批已通过）——否则返回拒绝错误，superspace 不落。
- chrome-mcp-server 桥已连接（`/ws`、`/ping` 通）。

## 后置（成功后的领域状态变更）

- list/messages：经注入的 `store` 幂等落库 `Conversation`（`(platform, external_id)` 去重）与
  `Message`（`external_msg_id` 去重，`source=history`，role 映射 hr/user）。`role=hr` 入库后触发回复任务（后端 P1）。
- send：`source=agent` 消息落库；发送成功状态（loading→delivery→read）在后续 sync 复查。

## Recovery（失败恢复，指向 doc 15）

| 失败 | 策略 |
|---|---|
| `chrome_javascript` 被拒/报错 | list/messages 降级 `chrome_get_web_content` DOM 兜底（写 warning）；send 直接失败返回 `error` |
| `external_id` 不匹配当前选中会话 | 不自动点击切换；返回明确 `error`，请真人/agent 先切到该会话 |
| list 无 Vue `friendList` 且 DOM 空 | 返回 `error`，通知用户确认在聊天页且已登录 |
| send 按钮仍 `disabled`（输入事件未生效） | 返回 `error`，提示改用 `chrome_fill_or_select` / `chrome_keyboard` 交互兜底（方案 §3.4 step4） |
| 消息落库失败 | 不中断，记入 `errors`，返回已读数据 |

## 异常（可预见的失败与处理）

| 异常 | 处理 |
|---|---|
| 浏览器适配器未接线（`BROWSER_MCP_ENABLED=false`） | list/messages 走 `raw_*` 注入或返回 `error`；send 返回 `error` |
| `operation` 非法 | `error` 枚举合法取值 |
| send 未 `approved` | 拒绝，提示先过 doc 14 审批 |
| 反检测（页面被检测关闭） | 返回 `error`，遵循方案 §7：只做已加载只读 + 人工打开路径 |

---

## 接线说明（对接未来 agent，doc 06 skill_router）

```python
# 目录名含连字符，连线时重命名为合法包名 boss_chat（与 boss_extract_jobs 一起处理）。
# 未接线独立运行：进技能目录顶层导入（tests/conftest.py 已注入 sys.path）。


class ChatStoreAdapter:  # 接线点：把 backend ConversationService/MessageService 包成本工具契约
    def __init__(self, svc):
        self._svc = svc

    async def upsert_conversation(self, user_id, conv):
        # POST /api/v1/conversations
        #   { platform:"boss", external_id: conv["external_id"], hr_name, job_title,
        #     job_id: <关联岗位id>, hr_id: <关联HR id> }
        #   幂等：同 (platform, external_id) 已存在则返回既有会话
        ...

    async def append_messages(self, user_id, conversation_id, msgs):
        # POST /api/v1/conversations/{id}/messages
        #   [{ external_msg_id, role: item-friend?"hr":"user", content, source:"history", sent_at }]
        ...


chat_svc = BossChatService(
    adapter=BrowserToolAdapter(),
    store=ChatStoreAdapter(ConversationService(db)),
)
result = await chat_svc.run(user_id=1, operation="send", approved=True, text="你好")
```

**映射契约**（集成层负责）：
- `BrowserToolAdapter.call_tool("chrome_javascript", {"code": 注入后脚本})` → 返回 `ToolResult{ok, data}`，
  `data` 即脚本 `return` 的对象（`{ok, conversations|messages|sent...}`）。
- `list` 的 `external_id` → `Conversation.external_id`；Vue 的 `uniqueId`/`friendId`/`encryptJobId` 备选。
- `messages[].role`（item-friend→hr / item-mine→user）→ `Message.role`（枚举 `user/hr/agent/system`）。
- `send` `source=agent`；list/messages 历史同步 `source=history`。

## 未实现（严格按方案 §8.2 未确认，勿臆造）
- **发简历（Q9）**：方案标记点击后流程未实测、属高风险写操作。需先在**测试会话**真实验证一次
  对话框流程 + 后端请求（方案 §8.3.1），再补 `operation=send_resume`。当前不自动实现。
- WebSocket 主动收/重连：只走已加载只读 + `historyMsg`/`history/pull` 请求式同步（方案 §7.4）。