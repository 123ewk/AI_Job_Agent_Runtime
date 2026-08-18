# BOSS直聘 HR聊天页 操作方案 V1.0

> 文档类型：逆向网页分析结果（HR 聊天自动化管线）
> 分析日期：2026-08-15
> 分析执行：真实浏览器（真人手动打开页面）+ Chrome 扩展 MCP 通道（browser-mcp-lite，无 CDP 调试会话）
> 所属项目：AI 求职 Agent（Chrome Extension + FastAPI 后端）
> 适用分支：`feature/phase2-backend-api-v2`
> 对应需求：`docs/分析需求/BOSS直聘页面信息分析需求_V1.0.md` 第 3 章

---

## 0. 页面访问记录（分析对象）

| 项 | 值 |
|---|---|
| 页面 URL | `https://www.zhipin.com/web/geek/chat` |
| 页面标题 | `BOSS直聘` |
| 页面框架 | 独立聊天 SPA：`fe-zhipin-geek/web/chat-new/v5519/`（webpack chunk 全局名 `webpackChunkGeekChat`） |
| 登录态 | 已登录（渲染出真实会话列表：7 个会话） |
| 当前选中会话 | 黄先生（江苏环益童心信息科技 · 区域人事），右侧显示 3 条 HR 消息 + 职位卡片 |
| 访问方式 | 真人手动打开（扩展通道只读；CDP 主动导航会被 Boss 检测关闭，见文档1 §8） |

**关键结论先行**：
- 会话列表与聊天记录均为 **CSR + 懒加载**；
- 聊天记录 API `GET /wapi/zpchat/geek/historyMsg`，**每页 20 条，`maxMsgId` + `page` 向上翻页**；
- 会话 ID / HR ID / 职位 ID 等标识符均可从 Vue 数据或 `friendList` API 明文获取；
- 实时收发走 **WebSocket**（`/wapi/zpchat/config/ws`），需谨慎（见 §8）。

---

## 1. 会话列表（Q6，实测）

### 1.1 DOM 结构

```
div.chat-conversation                  ← 会话列表区
└── ul
    └── li[role="listitem"]            ← 单会话项
        └── div.friend-content-warp
            └── div.friend-content[.selected]   ← 选中态加 .selected，含 d-c="62001" 属性
                ├── div.figure > img.image-circle    ← HR 头像
                └── div.text
                    ├── div > span.time              ← 时间（07月25日）
                    ├── div.title-box > span.name-box
                    │   ├── span.name-text           ← HR 名（黄先生）
                    │   ├── span                     ← 公司（江苏环益童心信息科技）
                    │   ├── i.vline
                    │   └── span                     ← 职位（区域人事）
                    └── div.gray.last-msg
                        ├── span.last-msg-text       ← 最后消息预览
                        └── div.user-operation       ← 操作图标（悬停出现）
```

实测单条 HTML 片段（黄先生）：

```html
<li role="listitem" class="">
  <div class="friend-content-warp">
    <div d-c="62001" class="friend-content selected">
      <div class="figure"><img src="https://img.bosszhipin.com/..._s.png.webp" class="image-circle"></div>
      <div class="text">
        <div><span class="time">07月25日</span></div>
        <div class="title-box">
          <span class="name-box">
            <span class="name-text">黄先生</span>
            <span>江苏环益童心信息科技</span><i class="vline"></i><span>区域人事</span>
          </span>
        </div>
        <div class="gray last-msg">
          <span class="last-msg-text">同学有兴趣了一下吗，有兴趣的话我可以给你介绍一下哦</span>
          <div class="user-operation"><img class="icon-operate list-operate"></div>
        </div>
      </div>
    </div>
  </div>
</li>
```

### 1.2 会话项承载字段 → 映射

| 展示字段 | DOM 位置 | 说明 |
|---|---|---|
| HR 名 | `span.name-text` | 如 `黄先生` |
| 公司 | `span.name-box > span`（第 2 个） | 如 `江苏环益童心信息科技` |
| 职位 | `span.name-box > span`（`i.vline` 后） | 如 `区域人事` |
| 最后消息 | `span.last-msg-text` | 如 `同学有兴趣了一下吗...` |
| 时间 | `span.time` | `07月25日`（会话列表为月/日） |
| 送达/已读 | 会话项文本 `[送达]`/`[已读]` | 部分会话可见 |
| 头像 | `img.image-circle` | `https://img.bosszhipin.com/...` |

### 1.3 会话 external_id（重点）

**从 API 或 Vue 数据取，不从 DOM 取**：

- API：`GET /wapi/zprelation/friend/geekFilterByLabel?labelId=0&encryptSystemId={encryptSystemId}` → 响应 `zpData.friendList[]`，每项含 `uniqueId`、`friendId`、`encryptBossId`、`encryptJobId`、`bossName` 等。
- Vue（当前选中会话 `$data.boss`，实测完整示例）：

```json
{
  "name": "黄先生",
  "avatar": "https://img.bosszhipin.com/...",
  "encryptBossId": "f574409d4c6ae4030Hd53ty0GFJR",   // ← HR external_id（去重锚点）
  "securityId": "0YrqPY34sRbvc-...",
  "encryptJobId": "e33fa46483cf468c0nF93N-6E1NT",     // ← 关联岗位 external_id
  "jobId": 557727313,
  "friendSource": 0,
  "friendId": 733519801,
  "uid": 733519801,
  "uniqueId": "733519801-0",                            // 会话 ID 候选（friendId-friendSource）
  "lastText": "同学有兴趣了一下吗..."
}
```

> **会话 `external_id` 建议**：用 `encryptBossId`（HR 侧 ID，与 `getBossData`/`historyMsg` 的 `bossId` 一致）；`uniqueId`（`friendId-friendSource`）亦可作备选。

### 1.4 数据来源与切换

- 列表数据来源：API `geekFilterByLabel`（响应 `zpData.friendList`）+ 本地 `unreadFriends` 合并（webpack `getMergedFriendsList(o, e.unreadFriends)`）。
- **切换会话**：点击会话项 → 触发 `on-click`/`handleOpenChat` 事件 → 右侧加载该 boss 的聊天记录（`getHistoryMessage`）。**切换 = 触发新 `historyMsg` 请求**（点击后 URL 不变，纯前端路由/状态切换）。

---

## 2. 聊天记录加载机制（Q7，重点确认：懒加载）

### 2.1 结论：**懒加载**（用户预判正确）

- `mounted()` 调用 `getHistoryMessage()` 加载**最近一页**；
- 聊天区**向上滚动到底部**（更早消息方向）→ `loadMore`/`loadNextPage()` 加载更早一页；
- 新消息通过 `history/pull` 轮询或 WebSocket 推送（见 §2.4）。

### 2.2 历史记录请求（实测 URL + 参数）

```
GET https://www.zhipin.com/wapi/zpchat/geek/historyMsg
    ?bossId=f574409d4c6ae4030Hd53ty0GFJR   # = encryptBossId
    &maxMsgId=0                              # 当前最早消息 mid（首次 0）
    &c=20                                    # 每页条数 = 20
    &page=1                                  # 页码
    &src=0                                   # = friendSource
    &securityId=0YrqPY34sRbvc-...            # 会话 securityId
    &gid=                                    # 群组 ID（非群聊为空，同 groupId）
```

webpack 源码考古确认的参数构造：

```js
f = { bossId: u, groupId: l, maxMsgId: e.msgMinId, c: e.pageSize, page: e.page, src: d, securityId: p, gid: l }
// e.msgMinId = 当前已加载消息中最小的 mid（向上翻页时光标）
// 响应：{ code, zpData: { ...消息数组 } }
```

**关键参数语义**：
- `maxMsgId`：向上加载更早消息的**游标**（当前最早一条消息的 `mid`），首次为 0 → 返回最新一页；再次加载传已加载最小 `mid`。
- `c`：每页 **20 条**（实测 URL `c=20`）。

### 2.3 新消息拉取

```
GET /wapi/zpmsg/history/pull?type=0&lastId=365459271607296&secretId=...
```

- `lastId` = 已收到最新消息 `mid`（轮询增量拉取）。

### 2.4 实时通道（WebSocket）

- 页面加载时请求 `/wapi/zpchat/config/ws`（获取 WS 配置），实时消息走 WebSocket。
- ⚠️ 自动化需谨慎：WS 连接的维持与消息推送时序未完全确认（见 §8 未确认项）。

### 2.5 消息 DOM（role 区分）

```html
<li data-mid="367615732506625" class="message-item item-friend">
  <div class="item-time"><span class="time">07-24 18:32</span></div>
  <div class="message-content">
    <div class="figure"><img class="image-circle" src=".../avatar..."></div>
    <div class="text">
      <p><span class="text-content">同学你好呀，我们在招聘暑期校园兼职...</span></p>
    </div>
  </div>
</li>
```

| 元素 | 类名/属性 | 说明 |
|---|---|---|
| 消息项 | `li.message-item` | 角色由 `item-*` 区分 |
| **role=hr** | `li.message-item.item-friend` | HR 发来的（本次实测 3 条均为此类） |
| **role=user** | `li.message-item.item-mine` | 自己发出的（本次视图无该类型，未实测到实例，由类名推断） |
| 消息 ID | `data-mid="367615732506625"` | **`external_msg_id` 候选（数字字符串）** |
| 内容 | `span.text-content` | 纯文本消息内容 |
| 时间 | `span.time` | `07-24 18:32` |
| 卡片消息 | `div.message-card-wrap` | 职位卡片/统计卡片（如「你与该职位竞争者PK情况」，含 `msg-blur` 模糊图——数量类信息被图片模糊） |
| 状态类 | `status-delivery` / `status-read` / `status-error` | 送达/已读/失败（webpack `msgStatusConfigs` 考古确认） |

消息对象数据结构（webpack 考古）：

```js
{ mid, messageType, status, fromName, type, text, isSelf, image?, sticker?, sound? }
// mid: 消息 ID（Number），messageType: "text"/"image"/"sticker"/"sound"...
```

### 2.6 消息 → MessageCreate 映射

| MessageCreate | 来源 | 说明 |
|---|---|---|
| `external_msg_id` | `li.message-item` 的 `data-mid`（或消息对象 `mid`） | 去重锚点 |
| `role` | `item-friend` → `hr`；`item-mine` → `user` | **枚举约束**：`user`/`hr`/`agent`/`system` |
| `content` | `span.text-content` | 纯文本；卡片/图片消息需单独处理（可存 `[卡片]` 占位或 JSON） |
| `sent_at` | `span.time`（`07-24 18:32`） | 会话内时间格式，注意跨年（无年份）需页面上下文推断 |
| `source` | 历史拉取 → `history` | 本轮首次同步的历史消息建议 `source=history` |

---

## 3. 输入框与发送（Q8，实测）

### 3.1 输入框 DOM

```html
<div contenteditable="true" id="chat-input" class="chat-input"></div>
```

- **`contenteditable` div（富文本）**，非 textarea；`id=chat-input`，class `chat-input`。
- 输入提示文案在发送按钮旁：`按Enter键发送，按Ctrl+Enter键换行`。

### 3.2 发送按钮

```html
<button class="btn-v2 btn-sure-v2 btn-send disabled">发送</button>
```

- 空输入时带 `.disabled`；有内容时去除（`enableSubmit` 计算属性控制）。

### 3.3 发送触发（webpack 源码确认）

```js
// keydown: Enter 且 !shiftKey → preventDefault + handleSend
if ("Enter" === e.key || e.shiftKey || (e.preventDefault(), this.handleSend()))
// 实际条件：key==="Enter" && !e.shiftKey 才发送；Shift+Enter 换行

handleSend() {
  var e = this.inputValue.trim();
  if (e) {
    en.A.sendMessage(
      { uid: this.boss.friendId, friendSource: this.boss.friendSource, encryptUid: this.boss.encryptBossId },
      e, "text"
    );
    this.inputValue = "";      // 发送后清空
    this.scrollToBottom();     // 滚到底部
  }
}
```

- 发送参数：`uid=friendId`、`friendSource`、`encryptUid=encryptBossId` + 文本 + 类型 `"text"`。
- **发送通道**：`sendMessage` 模块实现未在本次考古中定位（压缩格式差异），疑走 WebSocket（页面有 `/wapi/zpchat/config/ws`）——**未确认**（见 §8）。

### 3.4 预写输入框（自动化操作步骤）

1. 定位 `div#chat-input.chat-input`；
2. 写入内容并触发 Vue 输入监听：`el.textContent = msg`（或 `innerHTML`）→ 派发 `input` 事件（Vue 的 `inputValue` 由 `input` 事件更新）；
3. 若用原生事件不生效，可尝试直接派发 `KeyboardEvent('input')` 或 `new Event('input', {bubbles:true})`；
4. 确认发送按钮 `.disabled` 消失后触发发送（见下）。

### 3.5 发送（自动化操作步骤）

- **方式 A（推荐，走页面原生逻辑）**：聚焦 `#chat-input` → 预写文本 → 派发 `keydown` Enter（`key='Enter', code='Enter', keyCode=13, bubbles=true`）→ 页面 `handleSend` 触发 → 消息经 `sendMessage` 发出。
- **方式 B**：预写后点击 `button.btn-send`（需先确认 `.disabled` 已去除）。
- **成功判定**：
  1. 输入框 `inputValue` 被清空（`#chat-input` 文本为空）；
  2. 消息区新增 `li.message-item.item-mine`（含本地生成的 `data-mid`）；
  3. 消息状态类流转 `status-loading → status-delivery → status-read`（发送中 → 送达 → 已读）。

---

## 4. 发简历（Q9，入口已确认 / 流程部分未确认）

### 4.1 入口 DOM（实测）

```html
<div data-v-47cdaa3f="" aria-label="" d-c="62009" class="toolbar-btn tooltip tooltip-top"> 发简历 </div>
```

- 位置：输入区上方工具栏（与发送按钮同区域）。
- 其他入口：`a`（文本「简历」）指向简历制作页 `https://cv.zhipin.com`（模板，非发送）。

### 4.2 点击后流程（部分推断，未实测点击）

1. 点击「发简历」→ 预期弹出**简历选择对话框**（页面 DOM 中存在 `div.upload-resume-dialog` 与 `upload-select-dialog`，即上传/选择简历对话框容器）；
2. 选择已有简历（或上传）→ 确认 → 发送；
3. 成功判定：消息区出现 `item-mine` 的简历卡片消息（`div.message-card-wrap` 中简历类卡片）。

> ⚠️ **点击「发简历」属于高风险写操作**（会真实触发展示简历给 HR），本次分析**未实测点击**。流程第 2/3 步为基于 DOM 与 webpack 线索的推断，落地前需在测试会话中真人验证一次。

### 4.3 发简历后端 API

- **未确认**（本次只读分析未捕获到发简历请求 URL；webpack 中 `sendResume`/`deliverResume` 关键词未命中发送模块）。

---

## 5. 其他聊天元素（Q10）

| 元素 | DOM | 说明 |
|---|---|---|
| 会话筛选 | `ul > li`：全部/未读/新招呼/仅沟通/更多 | 过滤会话列表（`geekFilterByLabel` labelId 变化） |
| 搜索 | `input[placeholder="搜索30天内的联系人"]` | 会话搜索 |
| 附件简历 | `li.resume-box-template > a` → `https://cv.zhipin.com` | 简历制作入口 |
| 表情 | `[class*="sticker"]` / `/wapi/zpchat/sticker/get/sticker` | 表情包（发送 `"sticker"` 类型） |
| 埋点 | `sendAction({action, p, p2...})` | 页面大量埋点，不干预 |
| 草稿 | `sessionStorage["boss-chat-draft-{uid}"]` | 输入草稿自动保存（预写时注意覆盖） |

---

## 6. 自动化操作方案（Skill → MCP 路径）

### 6.1 会话列表拉取 → ConversationCreate

```js
// 1) 从 Vue store 取 friendList（页面已加载，零新增请求）或读 DOM
const items = [...document.querySelectorAll('.friend-content')].map(el => ({
  name:      el.querySelector('.name-text')?.textContent.trim(),
  company:   el.querySelector('.name-box > span:nth-child(2)')?.textContent.trim(),
  position:  el.querySelector('.name-box > span:last-of-type')?.textContent.trim(),
  lastMsg:   el.querySelector('.last-msg-text')?.textContent.trim(),
  time:      el.querySelector('.time')?.textContent.trim(),
}));
// 2) external_id：从 Vue $data.boss 或 friendList API 数据取
//    encryptBossId / friendId / uniqueId / encryptJobId
// 3) 落库：POST /api/v1/conversations
//    { platform:'boss', external_id: boss.encryptBossId,
//      hr_name: boss.name, job_title: <boss.jobName|职位名>,
//      job_id: <关联岗位id>, hr_id: <关联HR id> }
//    幂等：同 (platform, external_id) 已有则返回既有会话
```

### 6.2 聊天记录拉取（懒加载处理）→ MessageCreate

```js
// 已加载页：遍历 .message-item，取 mid / role / text-content / time
// 更早消息：向上滚动容器触发 loadNextPage，或直接调用内部 API：
//   GET /wapi/zpchat/geek/historyMsg
//     ?bossId={encryptBossId}&maxMsgId={最早mid}&c=20&page={page}&src={friendSource}&securityId={securityId}
// 增量新消息：GET /wapi/zpmsg/history/pull?type=0&lastId={最新mid}&secretId={...}
// 落库：POST /api/v1/conversations/{id}/messages
//   { external_msg_id: data-mid, role: item-friend?'hr':'user',
//     content: text-content, source: 'history'|'manual', sent_at: time }
//   role=hr 自动触发 hr_reply 回复任务（后端 P1）
// 对接 sync 端点：POST /api/v1/conversations/{id}/sync（当前 stub → 由本方案实现真正同步）
```

### 6.3 预写 + 发送（回写 Boss）

```js
const input = document.querySelector('#chat-input');
// 1) 预写
input.textContent = replyText;
input.dispatchEvent(new InputEvent('input', { bubbles: true })); // 更新 Vue inputValue
// 2) 确认按钮可用
if (document.querySelector('button.btn-send').classList.contains('disabled')) {
  // 事件未生效：改派发 compositionend / 设置 innerHTML 后派发 input
}
// 3) 触发发送：派发 Enter
input.dispatchEvent(new KeyboardEvent('keydown', {
  key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true
}));
// 4) 成功判定：input 清空 && 出现 item-mine 新消息
```

### 6.4 发简历

```js
// 1) 点击 .toolbar-btn（文本"发简历"）
// 2) 对话框（.upload-resume-dialog）中选择简历并确认
// 3) 成功判定：消息区出现简历卡片 item-mine
// ⚠️ 高风险写操作：落地前真人验证一次完整流程
```

---

## 7. 反检测注意事项

1. **真人打开页面**：任何 CDP/Playwright 主动导航到 zhipin 会被检测关闭（本项目实测，见文档1 §8）。扩展通道 + 真人打开为唯一可用路径。
2. **只读优先**：会话列表/记录读取应优先走**已加载 Vue 数据/DOM**（零新增请求）；确实需要翻页时，向上滚动由真人操作或谨慎触发（滚动加载 = 新请求）。
3. **写操作最小化**：发送/发简历是真实对外行为，**必须用户确认后执行**，且频率要低（模拟真人节奏）。
4. **WebSocket 风险**：实时通道协议未完全确认，自动化**不要主动重连/保持 WS**（避免异常指纹），以 `historyMsg` + `history/pull` 的请求式拉取为主。
5. **红线（本项目 V2.0）**：content script 禁止 DOM 抽取，数据一律经 **Skill → MCP 同步通道**；本方案即按此设计。
6. **消息状态**：`status-error` 存在（发送失败重发 `handleResend`），自动化需处理发送失败场景。

---

## 8. 附录：已确认 / 未确认项

### 8.1 已确认（本次实测）

- 会话列表 API `geekFilterByLabel` → `zpData.friendList`（含 uniqueId/friendId/encryptBossId/encryptJobId）。
- 历史记录 API `historyMsg`（懒加载，`maxMsgId`+`c=20`+`page`+`src`+`securityId`+`bossId`），响应 `zpData`。
- 增量拉取 API `history/pull`（`lastId`=最新 mid）。
- 实时通道：`/wapi/zpchat/config/ws`（WebSocket 配置）。
- 输入框 `#chat-input`（contenteditable），Enter 发送 / Shift+Enter 换行，按钮 `button.btn-send`。
- 发送参数 `{uid:friendId, friendSource, encryptUid:encryptBossId} + text + "text"`。
- 消息 DOM `li.message-item.item-friend/.item-mine` + `data-mid` + `span.text-content` + `span.time`。
- 发简历入口 `.toolbar-btn`（文本「发简历」，d-c=62009）。
- 消息状态类 `status-loading/delivery/read/error`。

### 8.2 未确认（勿臆造）

- `sendMessage` 的底层通道（HTTP or WS）与消息体格式（webpack 压缩未定位到定义处）。
- 发简历点击后的**完整交互流程**（弹出对话框 → 选简历 → 确认）与后端 API（未实测点击）。
- `item-mine` 消息的实际 DOM（本次视图无自己发的消息，由类名与前端逻辑推断）。
- `historyMsg` 的请求方法（GET 由实测 URL 推测，重放未验证）；`friendList` 响应中字段与 `geekFilterByLabel` 的 `encryptSystemId` 来源。
- WebSocket 协议帧格式、心跳、消息推送事件名。

### 8.3 后续建议

1. 用**测试会话**（真实用户允许的前提下）真人点击一次「发简历」，记录对话框流程与后端请求，补齐 Q9 完整链路。
2. 若需 `description`/`job_detail`，另开岗位详情页只读分析（同文档1 §9.3）。
3. `sync` 端点落地时，按 §6.2 的 `historyMsg`/`history/pull` 双通道实现增量同步。
