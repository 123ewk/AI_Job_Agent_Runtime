# BOSS直聘 页面信息分析需求文档 V1.0

> 文档类型：分析需求（Analysis Requirements，供另一 AI 执行页面分析）
> 创建日期：2026-08-15
> 所属项目：AI 求职 Agent（Chrome Extension + FastAPI 后端）
> 适用分支：`feature/phase2-backend-api-v2`
> 状态：**待执行** —— 本仓库内 Claude 受 Boss 反自动化检测限制，无法自行导航页面，故撰写本文档交由具备真实浏览器/页面访问能力的分析 AI 执行。

---

## 0. 文档目的与执行方式

本仓库的 AI 求职 Agent 需要在 BOSS直聘 上实现两条自动化管线：

1. **岗位入库管线**：从岗位列表页抓取每个岗位的数据，写入后端数据库。
2. **HR 聊天自动化管线**：在聊天页读取 HR 聊天列表与聊天记录、预写输入框、发送消息、发送简历。

仓库内 Claude 无法直接访问这两个页面（Boss 反自动化检测会把受控浏览器的导航返回/关闭，已实测确认），因此本需求文档将**分析任务外包给另一 AI**。执行者（下称「分析 AI」）应：

- 使用**能访问目标页面的真实浏览器**（已登录态）打开下述两个 URL；
- 遵守第 4 章「反自动化约束」，**尽量只读用户已加载页面 DOM、零新增 zhipin 请求**；
- 按第 2 / 3 章的任务逐项产出分析结论；
- 最终按第 5 章要求输出**两份 MD 文档**。

---

## 1. 项目背景与目标数据结构（后端契约）

### 1.1 系统简介

| 层 | 技术 | 职责 |
|---|---|---|
| 前端 | Chrome Extension（Vue3 + TS + Vite + Pinia） | 用户界面：岗位管理 / 聊天 / 简历 / 统计 |
| 后端 | FastAPI + PostgreSQL + Redis | 数据落库、评分、任务队列、会话管理 |
| 数据链路 | 前端抓取 → `POST /api/v1/jobs` 落库 → Agent 评分（≥60 进 chatting）→ 聊天页与 HR 沟通 | 当前目标 |

岗位数据流向：**BOSS 岗位页 → 提取 → `POST /api/v1/jobs` → 评分事件驱动 → 前端展示**。
聊天数据流向：**BOSS 聊天页 → 同步 → `POST /api/v1/conversations/...` → Agent 回复 → 回写 Boss 输入框**。

### 1.2 目标数据契约（分析 AI 必须以此为准映射页面字段）

#### A. 岗位（落库目标）

端点：`POST /api/v1/jobs`（前缀 `/api/v1`，单用户 `user_id=1`，无需鉴权头）。
**幂等去重**：同 `(platform, external_id)` 已存在时静默返回已有记录（非 409）。
新岗位默认 `status="discovered"`；评分**不随 POST 触发**（事件驱动）。

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `platform` | string | 否 | ≤30 | 默认 `"boss"` |
| `external_id` | string | **是** | ≤100 | **平台侧职位 ID（去重锚点）** |
| `title` | string\|null | 否 | ≤300 | 职位名称 |
| `company` | string\|null | 否 | ≤200 | 公司名称 |
| `salary` | string\|null | 否 | ≤100 | 薪资范围（原文，如 "25K-40K"） |
| `location` | string\|null | 否 | ≤200 | 工作地点 |
| `description` | string\|null | 否 | - | 职位描述 |
| `source_url` | string\|null | 否 | ≤500 | 职位来源链接 |
| `hr_id` | int\|null | 否 | - | 关联 HR ID（可选） |

#### B. HR

端点：`POST /api/v1/jobs/hr`（幂等去重 `(platform, external_id)`）。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `platform` | string | 否 | ≤30，默认 `"boss"` |
| `external_id` | string | **是** | ≤100，平台侧 HR ID（去重锚点） |
| `name` | string\|null | 否 | ≤100 |
| `company` | string\|null | 否 | ≤200 |
| `position` | string\|null | 否 | ≤200 |

#### C. 会话（聊天列表 → 落库）

端点：`POST /api/v1/conversations`。同 `(platform, external_id)` 已存在时直接返回已有会话。
活跃会话并发上限 **3**（超出 409）。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `platform` | string | 否 | ≤30，默认 `"boss"` |
| `external_id` | string | **是** | ≤100，平台侧会话 ID |
| `hr_name` | string\|null | 否 | ≤100 |
| `job_title` | string\|null | 否 | ≤200 |
| `job_id` | int\|null | 否 | 关联职位 ID |
| `hr_id` | int\|null | 否 | 关联 HR ID |

#### D. 消息（聊天记录 → 落库）

端点：`POST /api/v1/conversations/{conversation_id}/messages`。
**若 `role=hr`，自动触发创建 `hr_reply` 回复任务（P1）**。
去重：`external_msg_id` 已存在时跳过写入返回已有消息。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `external_msg_id` | string\|null | 否 | ≤100，平台侧消息 ID（去重） |
| `role` | string | **是** | 枚举：`user` / `hr` / `agent` / `system` |
| `content` | string | **是** | 消息内容 |
| `source` | string | 否 | 枚举：`manual` / `agent` / `history`；未传按 role 推断 |
| `sent_at` | datetime\|null | 否 | 发送时间，空则当前时间 |

#### E. 同步端点

`POST /api/v1/conversations/{conversation_id}/sync` —— 触发 Chrome Skill 拉取 Boss 页面消息并去重落库。**当前为 stub**（返回 0 条）。分析 AI 产出的方案应能指导未来实现真正同步。

---

## 2. 分析任务 1：岗位列表页

### 2.1 页面与访问方式

- URL：`https://www.zhipin.com/web/geek/jobs?_security_check=1_1786694650424`
- 说明：`_security_check` 参数为访问时动态生成，可能随登录态/时间变化。分析 AI 使用**自己登录态下的同构 URL**（`/web/geek/jobs`）即可。

### 2.2 必须回答的问题

#### Q1 数据来源判定
- 岗位列表数据是 **SSR（服务端渲染在 HTML）** 还是 **CSR（前端 JS 请求 API 后渲染）**？
- 若是 API：定位返回岗位列表的 XHR/fetch 请求，给出 **URL / method / query 参数 / 响应 JSON 结构**。
- 响应 JSON 中岗位数组的键名（历史线索：旧版为 `zpData.jobList`，需确认当前版本）。

#### Q2 岗位卡片 DOM 结构
- 岗位**列表容器**与**单卡片容器**的选择器/CSS 类名。
- 历史线索（需多级 fallback，Boss 会改版）：`job-card-box` / `job-card-wrapper`（旧 `job-list-box`）。
- 每张卡片各字段的定位方式（CSS class / data 属性 / 相对结构）：
  - 职位标题
  - 薪资
  - 公司名称
  - 工作地点/城市
  - 职位详情链接（通常含 `external_id`）
  - 标签/福利（可选）

#### Q3 external_id 提取
- 平台侧职位 ID 从哪取？候选：
  - 详情页 URL 中的数字 ID（如 `/job_detail/{id}.html`）
  - 卡片 DOM 的 `data-*` 属性
  - API 响应字段
- 给出**确切的提取位置与示例值**。

#### Q4 分页 / 滚动加载机制
- 列表是**分页（翻页）**还是**无限滚动（懒加载）**？
- 滚动到底的触发条件、加载更多岗位的网络请求形态（URL / 参数如 `page` / `query`）。

#### Q5 岗位详情页（可选增强，用于 `description`）
- 详情页 URL 模式？`description` 在详情页的 DOM 位置？
- 若单页抓详情成本过高，说明「仅列表字段落库、description 留空」是否可接受（后端允许 null）。

### 2.3 落库方案（输出文档 1 时必须包含）

- **方案 A：DOM 提取** —— 读取用户已加载页面 DOM，零新增 zhipin 请求（推荐，最稳，符合第 4 章约束）。
- **方案 B：API 监听/重放** —— 拦截 `zpData.jobList` JSON 或重放列表请求。
- 对每个方案给出：提取步骤、字段映射表（页面 → `JobCreate`）、可靠性、反检测风险、伪代码。
- 明确「每条岗位数据如何落到数据库」：映射 → `POST /api/v1/jobs`（幂等去重）。

---

## 3. 分析任务 2：聊天页

### 3.1 页面与访问方式

- URL：`https://www.zhipin.com/web/geek/chat`
- 注意：聊天页通常需要**已存在会话**（即用户曾与某 HR 沟通过）才能看到列表与记录。

### 3.2 必须回答的问题

#### Q6 HR 聊天列表
- 会话列表**容器 / 单会话项**的 DOM 结构。
- 每个会话项承载的字段：HR 名、职位名、公司名、最后一条消息预览、时间、未读标记。
- 会话 `external_id` 从哪取（候选：会话项 data 属性 / 点击后 URL / API 响应）。
- 列表数据来源：DOM 渲染 or API 请求（若 API，给出 URL/参数/响应结构）。
- **切换会话**的交互方式（点击会话项 → 触发什么）。

#### Q7 聊天记录加载机制（重点确认）
- **务必确认：聊天记录是一次性全量加载还是懒加载？**（用户预判为懒加载）
- 若懒加载：
  - 触发条件（点击会话后才加载？滚动到底加载更早消息？）
  - 每次加载多少条？请求形态（URL、参数如 `since_id` / `before_id` / 页码 / limit）。
- 消息 DOM 结构：每条消息容器、**role（user/hr）区分方式**、内容、时间、消息 ID（`external_msg_id` 候选）。

#### Q8 输入框与发送
- 输入框 DOM：标签类型（textarea / contenteditable）、placeholder、class、是否富文本。
- **如何预写内容**（写值 + 触发 input 事件序列）。
- 发送触发方式：点击发送按钮 / 快捷键（Enter / Ctrl+Enter）——给出按钮 class 与事件流。
- 发送成功后 DOM 变化（消息追加到列表、输入框清空）→ 如何据此确认发送成功。

#### Q9 发简历
- 「发送简历 / 简历」按钮或入口的 DOM 位置与 class。
- 点击后的交互流程：直接发送默认简历？弹出简历选择器？文件选择？
- 如何判定简历已发送成功（DOM 变化 / 系统提示）。

#### Q10 其他聊天相关元素（可选）
- 表情、附件、快捷回复、已读状态、会话搜索等对自动化有价值或需避开的元素。

### 3.3 自动化操作方案（输出文档 2 时必须包含）

- 聊天列表拉取 → 映射 `ConversationCreate` 落库。
- 聊天记录拉取（含懒加载处理）→ 映射 `MessageCreate` 落库 + `sync` 端点对接。
- 预写输入框 + 发送 → 回写 Boss 的伪代码（含事件触发顺序）。
- 发简历操作步骤。
- 反检测注意事项。

---

## 4. 反自动化约束（分析 AI 必须遵守）

> 来源：2026-08-14/15 本仓库实测结论（用户确认）。

1. **Boss 会检测自动化浏览器**：受控（CDP/Playwright）浏览器主动导航 `zhipin` 岗位页/聊天页会被检测，表现为 **页面自动关闭**（console 报「Scripts may close only the windows that were opened by them」）或**导航返回**。
2. **推荐策略**：**只读用户已加载页面 DOM、零新增 zhipin 请求** —— 由真人先打开页面，分析 AI 只读取已渲染 DOM + 已发生的网络请求记录，不主动发起新的 zhipin 请求。
3. 反爬其他特征：`security-check` / `verify-slider` 滑块验证 / IP 封禁。
4. **本项目红线**（V2.0 设计）：扩展 content script **禁止** DOM 数据抽取，岗位/聊天数据一律经 Skill → MCP 同步通道（`CHAT_CONVERSATIONS_EXTRACTED` 通道已废弃）。分析 AI 产出的方案应**默认落到「Skill→MCP」路径**，避免建议 content script 直抽 DOM。（本需求文档聚焦页面信息分析，具体落地通道由仓库后续决定。）

---

## 5. 输出要求（两份 MD 文档）

分析 AI 需产出 **两份独立的 Markdown 文档**（建议各 100–200 行，含代码块），放置于仓库 `docs/` 下（文件名由分析 AI 自定，中文命名，版本号如 `_V1.0`）。

### 文档 1：岗位页数据提取落库方案

必须包含：

- 数据来源判定（SSR/API）与岗位列表请求详情。
- 完整 DOM 结构树（列表容器 + 卡片 + 各字段定位）。
- `external_id` 提取位置与示例。
- 分页/滚动加载机制。
- 字段映射表（页面字段 → `JobCreate` 字段，含类型/约束/示例值）。
- 推荐提取方案（DOM vs API）与伪代码。
- 落库链路：提取 → 映射 → `POST /api/v1/jobs`。
- 反检测注意事项。

### 文档 2：HR 聊天页操作方案

必须包含：

- 聊天列表 DOM + `external_id` 提取 + 映射 `ConversationCreate`。
- **聊天记录加载机制结论**（一次性 or 懒加载；若懒加载给出触发条件、请求参数、每次条数）。
- 消息 DOM + role 区分 + 映射 `MessageCreate`。
- 输入框预写 + 发送的完整操作步骤与伪代码。
- 发简历操作步骤。
- 反检测注意事项。

### 通用要求

- 每份文档开头注明：页面 URL、分析时间、登录态说明、页面版本特征（如是否有 `_security_check`、URL 结构）。
- 每个 DOM 结论给出**实测示例**（真实 class 名、data 属性、示例值），不要臆造。
- 对无法确认的项，明确标注「未确认」，不要猜测。
- 若发现对项目重要的额外页面信息（登录态、验证码、埋点、URL 规律等），作为附录写入。

---

## 6. 已有线索汇总（供分析 AI 参考，需验证）

以下为本仓库此前勘察得到的线索，**分析 AI 必须实测验证，不得直接照抄**：

| 线索 | 状态 |
|---|---|
| 岗位列表 API 返回键名 `zpData.jobList`（旧版） | 待验证当前版本 |
| 岗位卡片容器 `job-card-box` / `job-card-wrapper`（旧 `job-list-box`） | 待验证（需多级 fallback） |
| Boss 检测自动化 → 页面自动关闭 / 导航返回 | 已确认（2026-08-15） |
| `_security_check` 参数与反自动化相关 | 已确认出现，含义待确认 |
| 岗位详情 URL 形如 `/job_detail/{id}.html` | 待验证 |
| 聊天记录为懒加载 | 用户预判，待确认 |

---

## 7. 相关文档索引

- 后端接口契约：`docs/接口文档/jobs.md`、`docs/接口文档/conversations.md`（字段级权威）
- 数据库设计：`docs/数据库设计文档/`（03-岗位与HR模块 / 04-会话与消息模块）
- 设计权威：`docs/AI求职Agent_设计文档_V2.0/`（V2.0 红线见 doc 11 §4.6/§13、doc 13 §2）
- 历史勘察：见仓库记忆 `job-data-pipeline` / `chrome-cdp-setup`（本文档已提取关键结论）
