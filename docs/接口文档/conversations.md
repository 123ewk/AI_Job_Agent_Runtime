# 会话管理模块（Conversations）

> 前缀：`/api/v1/conversations` · 代码：`backend/app/api/v1/conversations.py` · DTO：`backend/app/schema/conversation.py`

会话是 Agent 与 HR 沟通的线程，每条消息全量落库。提供会话列表、消息历史、手动发送、同步等接口。

**路由顺序注意**：`GET /conversations/unreplied/check` 为多段路径，与单段 `/{conversation_id}` 不冲突。

## 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/conversations` | 获取会话列表（分页） |
| GET | `/api/v1/conversations/{conversation_id}` | 获取会话详情 |
| POST | `/api/v1/conversations` | 创建会话 |
| PUT | `/api/v1/conversations/{conversation_id}` | 更新会话元数据 |
| POST | `/api/v1/conversations/{conversation_id}/close` | 关闭会话 |
| GET | `/api/v1/conversations/{conversation_id}/messages` | 获取消息历史 |
| POST | `/api/v1/conversations/{conversation_id}/messages` | 添加消息 |
| POST | `/api/v1/conversations/{conversation_id}/sync` | 从 Boss 页面同步新消息 |
| GET | `/api/v1/conversations/unreplied/check` | 检查未回复的 HR 消息 |

---

## 1. GET /conversations — 会话列表

按最后更新时间倒序排列（`order_by="updated_at"`）。

**Query 参数**：`page`（默认 1）、`page_size`（默认 20，1–100）

**响应 200** — `PaginatedResponse[ConversationResponse]`

```json
{
  "items": [
    {
      "id": 10,
      "user_id": 1,
      "platform": "boss",
      "external_id": "boss_conv_100",
      "hr_name": "王经理",
      "job_title": "Python 后端工程师",
      "job_id": 1,
      "hr_id": 5,
      "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "status": "active",
      "last_synced_at": null,
      "created_at": "2026-08-10T10:00:00Z",
      "updated_at": "2026-08-10T10:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 会话 ID |
| `user_id` | int | 用户 ID |
| `platform` | string | 平台标识（默认 boss，≤30） |
| `external_id` | string | 平台侧会话 ID（≤100） |
| `hr_name` | string\|null | HR 姓名（≤100） |
| `job_title` | string\|null | 职位名称（≤200） |
| `job_id` / `hr_id` | int\|null | 关联职位 / HR |
| `uuid` | UUID | 会话 UUID |
| `thread_id` | UUID | LangGraph thread_id（执行上下文延续用） |
| `status` | string | active / waiting_hr / closed |
| `last_synced_at` | datetime\|null | 最后同步时间 |
| `created_at` / `updated_at` | datetime | 创建 / 更新时间 |

---

## 2. GET /conversations/{conversation_id} — 会话详情

**路径参数**：`conversation_id`（int）
**响应 200** — `ConversationResponse`（字段同上）
**错误**：404 `not_found`

---

## 3. POST /conversations — 创建会话

创建前检查**活跃会话并发数上限**（`DEFAULT_MAX_CONCURRENT_CHATS = 3`，硬编码常量），超限返回 409。
同平台同 `external_id` 已存在时直接返回已有会话。

**请求体** — `ConversationCreate`

```json
{
  "platform": "boss",
  "external_id": "boss_conv_100",
  "hr_name": "王经理",
  "job_title": "Python 后端工程师",
  "job_id": 1,
  "hr_id": 5
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `platform` | string | 否（默认 boss） | ≤30 |
| `external_id` | string | **是** | 平台侧会话 ID ≤100 |
| `hr_name` | string\|null | 否 | ≤100 |
| `job_title` | string\|null | 否 | ≤200 |
| `job_id` | int\|null | 否 | 关联职位 ID |
| `hr_id` | int\|null | 否 | 关联 HR ID |

**响应 201** — `ConversationResponse`（新会话 `status=active`）
**错误**：409 `conflict`（活跃会话数已达上限 3）

---

## 4. PUT /conversations/{conversation_id} — 更新会话

更新会话元数据（HR 姓名、职位标题、状态等），`exclude_unset=True` 部分更新。

**请求体** — `ConversationUpdate`

```json
{
  "hr_name": "李经理",
  "job_title": "高级后端工程师",
  "status": "waiting_hr",
  "last_synced_at": "2026-08-10T12:00:00Z"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `hr_name` | string\|null | HR 姓名 ≤100 |
| `job_title` | string\|null | 职位名称 ≤200 |
| `status` | string\|null | **枚举校验**：仅允许 `active` / `waiting_hr` / `closed`，非法值 422 |
| `last_synced_at` | datetime\|null | 最后同步时间 |

**响应 200** — `ConversationResponse`
**错误**：404 `not_found`、422（status 非法）

---

## 5. POST /conversations/{conversation_id}/close — 关闭会话

关闭（软关闭，`status="closed"`）后不再生成回复任务，但仍可查询历史消息。

**响应 200** — `StatusResponse`

```json
{ "status": "ok", "message": "会话已关闭" }
```

**错误**：404 `not_found`

---

## 6. GET /conversations/{conversation_id}/messages — 消息历史

按发送时间正序排列。

**Query 参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `limit` | int | 否 | 返回条数上限，默认 100 |

**响应 200** — `list[MessageResponse]`

```json
[
  {
    "id": 1,
    "conversation_id": 10,
    "user_id": 1,
    "external_msg_id": "boss_msg_1",
    "role": "hr",
    "content": "您好，看了您的简历很感兴趣",
    "source": "history",
    "sent_at": "2026-08-10T10:00:00Z",
    "created_at": "2026-08-10T10:00:00Z"
  }
]
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 消息 ID |
| `conversation_id` / `user_id` | int | 会话 / 用户 ID |
| `external_msg_id` | string\|null | 平台侧消息 ID（去重用，≤100） |
| `role` | string | user / hr / agent / system |
| `content` | string | 消息内容 |
| `source` | string | manual / agent / history |
| `sent_at` | datetime\|null | 发送时间 |
| `created_at` | datetime | 入库时间 |

---

## 7. POST /conversations/{conversation_id}/messages — 添加消息

添加消息到会话。**若是 HR 消息（`role=hr`），会自动触发创建 `hr_reply` 回复任务（P1）**（`_enqueue_reply_task`）。
`conversation_id` 由路径注入（路由会覆盖请求体中的值）。

**去重**：`external_msg_id` 已存在时跳过写入，返回已有消息。

**请求体** — `MessageCreate`

```json
{
  "external_msg_id": "boss_msg_2",
  "role": "user",
  "content": "好的，我这边随时可以面试",
  "source": "manual",
  "sent_at": "2026-08-10T10:05:00Z"
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `external_msg_id` | string\|null | 否 | 平台侧消息 ID ≤100 |
| `role` | string | **是** | **枚举校验**：user / hr / agent / system |
| `content` | string | **是** | 消息内容 |
| `source` | string | 否（默认 manual） | **枚举校验**：manual / agent / history；未传时按 role 推断：user→manual、agent→agent、hr→history、system→manual |
| `sent_at` | datetime\|null | 否 | 发送时间（为空时用当前时间） |

**响应 201** — `MessageResponse`
**错误**：404 `not_found`（会话不存在）、422（role/source 非法）

---

## 8. POST /conversations/{conversation_id}/sync — 同步新消息

触发 Chrome Skill 拉取 Boss 页面消息并去重落库。更新 `last_synced_at`。

> ⚠️ **当前为 stub**：`sync_boss_messages` 未实际拉取页面消息，返回 0，消息提示"同步完成，新增 0 条消息"。

**响应 200** — `StatusResponse`

```json
{ "status": "ok", "message": "同步完成，新增 0 条消息" }
```

**错误**：404 `not_found`

---

## 9. GET /conversations/unreplied/check — 未回复消息检查

返回所有**活跃会话**中「HR 已发但尚无非 HR 消息回复」的最后一条 HR 消息。判断逻辑（`get_unreplied_messages`）：
遍历每个活跃会话最近 50 条消息，若最后一条 HR 消息晚于最后一条非 HR 消息，则判定为未回复。

**响应 200** — 普通 dict（`count` + `messages`），`messages` 元素**不是** `MessageResponse`，而是如下结构：

```json
{
  "count": 2,
  "messages": [
    {
      "conversation_id": 10,
      "conversation_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "message_id": 3,
      "message_content": "方便约个时间面试吗？",
      "hr_name": "王经理",
      "job_title": "Python 后端工程师"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `count` | int | 未回复消息总数 |
| `messages` | array | 未回复项列表 |
| `messages[].conversation_id` | int | 会话 ID |
| `messages[].conversation_uuid` | string | 会话 UUID |
| `messages[].thread_id` | string | LangGraph thread_id |
| `messages[].message_id` | int | 最后一条 HR 消息 ID |
| `messages[].message_content` | string | 消息内容 |
| `messages[].hr_name` | string\|null | HR 姓名 |
| `messages[].job_title` | string\|null | 职位名称 |
