# 任务管理模块（Tasks）

> 前缀：`/api/v1/tasks` · 代码：`backend/app/api/v1/tasks.py` · DTO：`backend/app/schema/task.py`

任务是 Agent 执行的最小单元，支持优先级队列与状态流转。提供任务列表、详情、创建、取消、重试、审批与队列统计。

**路由顺序注意**：`GET /tasks/queue/stats` 与 `GET /tasks/{task_id}` 为不同段数路径，不冲突。

## 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/tasks` | 获取任务列表（分页 + 筛选） |
| GET | `/api/v1/tasks/{task_id}` | 获取任务详情 |
| POST | `/api/v1/tasks` | 创建任务并入队 |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消任务 |
| POST | `/api/v1/tasks/{task_id}/retry` | 重试失败任务 |
| GET | `/api/v1/tasks/{task_id}/approvals/pending` | 获取待处理审批 |
| POST | `/api/v1/tasks/{task_id}/approvals/approve` | 批准任务继续执行 |
| POST | `/api/v1/tasks/{task_id}/approvals/deny` | 拒绝任务执行 |
| GET | `/api/v1/tasks/queue/stats` | 获取任务队列统计 |

---

## 1. GET /tasks — 任务列表

**Query 参数**（`TaskFilterParams`，继承 `PaginationParams`）

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | int | 否 | 页码，默认 1 |
| `page_size` | int | 否 | 每页数量 1–100，默认 20 |
| `status` | string | 否 | 按状态筛选（见下方状态流转） |
| `type` | string | 否 | 按类型筛选 |
| `conversation_id` | int | 否 | 按会话筛选 |
| `job_id` | int | 否 | 按职位筛选 |

**响应 200** — `PaginatedResponse[TaskResponse]`

```json
{
  "items": [
    {
      "id": 100,
      "user_id": 1,
      "type": "hr_reply",
      "conversation_id": 10,
      "job_id": null,
      "status": "running",
      "priority": "P1",
      "retry_count": 0,
      "max_retries": 2,
      "progress": 0,
      "error_message": null,
      "result": null,
      "started_at": "2026-08-10T10:00:00Z",
      "completed_at": null,
      "created_at": "2026-08-10T10:00:00Z"
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
| `id` | int | 任务 ID |
| `user_id` | int | 用户 ID |
| `type` | string | 任务类型（见下） |
| `conversation_id` / `job_id` | int\|null | 关联会话 / 职位 |
| `status` | string | 任务状态 |
| `priority` | string | 优先级 P0–P3 |
| `retry_count` | int | 已重试次数 |
| `max_retries` | int | 最大重试次数 |
| `progress` | int | 进度百分比 0–100（update_status 写入，恒为 0 问题已修复） |
| `error_message` | string\|null | 错误信息（映射自 `task.error`） |
| `result` | object\|null | 任务结果（JSON） |
| `started_at` / `completed_at` | string\|null | 开始 / 完成时间（ISO） |
| `created_at` | string | 创建时间 |

---

## 2. GET /tasks/{task_id} — 任务详情

包含当前状态、进度、执行结果、错误信息。

**路径参数**：`task_id`（int）
**响应 200** — `TaskResponse`（字段同上）
**错误**：404 `not_found`

---

## 3. POST /tasks — 创建任务并入队

创建任务记录（`status=pending`）。`thread_id`：优先使用请求体传入值（延续已有上下文），未传则新建 UUID（LangGraph Checkpoint 锚点）。写入 Redis Stream 队列。

**请求体** — `TaskCreate`

```json
{
  "type": "hr_reply",
  "conversation_id": 10,
  "job_id": null,
  "priority": "P1",
  "params": { "draft": true },
  "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "triggering_message_id": 3
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `type` | string | **是** | 任务类型（见下） |
| `conversation_id` / `job_id` | int\|null | 否 | 关联会话 / 职位 |
| `priority` | string\|null | 否 | P0/P1/P2/P3；**为空时按类型自动分配**（见下表） |
| `params` | object\|null | 否 | 任务参数（JSON，落库为 `payload`） |
| `thread_id` | string\|null | 否 | 关联执行线程 ID；**传入优先**（非法 UUID 返回 400），未传则新建 |
| `triggering_message_id` | int\|null | 否 | 触发此任务的消息 ID |

**任务类型与自动优先级**（`TaskService._get_priority_by_type` 实际实现）

| type | 含义 | 自动优先级 |
| --- | --- | --- |
| `approval_resume` | 人工确认后继续 | **P0** |
| `recovery` | 故障恢复 | **P0** |
| `hr_reply` | HR 消息回复 | **P1** |
| `sync` | 数据同步 | **P1** |
| `user_initiated` | 用户主动触发 | **P2** |
| `proactive_chat` | 主动打招呼 | **P2** |
| `proactive_job` | 主动求职 | **P3** |
| `background_scan` | 后台扫描 | **P3** |
| （其他未知类型） | - | **P3**（兜底） |

> ✅ 已修复：docstring 优先级映射已与实现/文档统一（`proactive_job=P3`、`sync=P1`、`recovery=P0`）；
> `thread_id` 传入优先，非法值返回 400。**本文档以上表（实际实现）为准**。

**响应 201** — `TaskResponse`

---

## 4. POST /tasks/{task_id}/cancel — 取消任务

`TaskService.cancel` 行为（行锁防止并发状态变更）：

| 当前状态 | 行为 |
| --- | --- |
| `pending` | 标记 `canceled`，记录完成时间 |
| `running` | 标记 `canceled`（Runtime 下一检查点优雅退出） |
| `waiting_approval` | 标记 `canceled` |
| `succeeded` / `failed` / `canceled` | **终态，无操作**（不报错，返回当前任务） |

**响应 200** — `StatusResponse`

```json
{ "status": "ok", "message": "任务已取消" }
```

**错误**：404 `not_found`

---

## 5. POST /tasks/{task_id}/retry — 重试失败任务

`TaskService.retry` 行为：
- **仅限 `failed` 状态**；其他状态报 409（`TaskStateError`）。
- 受 `retry_count < max_retries`（默认 2）约束，超限报 409。
- **不是更新原任务，而是创建新任务**（保证审计完整），复用原 `thread_id`（续用 Checkpoint），`retry_count = 原值 + 1`。

**响应 200** — `TaskResponse`（新任务）
**错误**：404 `not_found`、409 `conflict`（非 failed / 超过最大重试次数）

---

## 6. GET /tasks/{task_id}/approvals/pending — 待处理审批

任务执行到需要人工确认的节点时，产生 `pending` 状态的 approval。

**响应 200** — `ApprovalResponse`；无待审批时返回 `null`

```json
{
  "id": 1,
  "task_id": 100,
  "user_id": 1,
  "type": "salary",
  "payload": { "salary": "25K-30K" },
  "status": "pending",
  "expires_at": "2026-08-10T10:00:20Z",
  "decided_at": null,
  "created_at": "2026-08-10T10:00:00Z"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 确认项 ID |
| `task_id` / `user_id` | int | 关联任务 / 用户 |
| `type` | string | 确认类型：salary / location / start_date / overtime / outsourcing / offsite / probation_salary |
| `payload` | object | 确认内容（JSON） |
| `status` | string | pending / approved / denied / timed_out |
| `expires_at` | string\|null | 超时时间（默认 20s） |
| `decided_at` | string\|null | 用户决策时间 |
| `created_at` | string | 创建时间 |

---

## 7. POST /tasks/{task_id}/approvals/approve — 批准继续执行

**请求体** — `TaskApproveRequest`（三个字段均为 Schema 必填）

```json
{
  "approval_id": 1,
  "approved": true,
  "user_note": "薪资可以接受"
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `approval_id` | int | **是** | 确认项 ID |
| `approved` | bool | **是** | 是否批准 |
| `user_note` | string\|null | 否 | 用户备注 |

**响应 200** — `StatusResponse`

```json
{ "status": "ok", "message": "已批准" }
```

**错误**：404 `not_found`（任务没有待处理的审批）

> ✅ 已修复：路由现在调用 `approval_service.approve(data.approval_id, user_id, data.user_note)`，
> 不再访问不存在的 `decision_payload`，`user_id` 来自 `CurrentUserDep`，approve 内部校验归属与 pending 状态。

---

## 8. POST /tasks/{task_id}/approvals/deny — 拒绝继续执行

拒绝后任务进入 `canceled` 终态，不再重试。决策结果写入 approval 记录。

**请求体**：无

**响应 200** — `StatusResponse`

```json
{ "status": "ok", "message": "已拒绝" }
```

**错误**：404 `not_found`（任务没有待处理的审批）

> ✅ 已修复：路由现在调用 `approval_service.deny(approval.id, user_id)`，`user_id` 来自 `CurrentUserDep`。

---

## 9. GET /tasks/queue/stats — 队列统计

**响应 200** — 普通 dict

```json
{
  "pending": 3,
  "max_concurrent": 3
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `pending` | int | 待处理任务数（status=pending） |
| `max_concurrent` | int | 最大并发数（**当前硬编码 3**，注释称可从 SettingsService 读取） |

---

## 任务状态流转（TaskStatus）

由 `TaskService._validate_status_transition` 定义，任何状态变更（API / Runtime 回调 / 超时）必须经过该校验，非法流转返回 409：

```
pending → running, canceled
running → waiting_approval, succeeded, failed, canceled, recovering
waiting_approval → running, canceled
recovering → running, failed
succeeded / failed / canceled → （终态，不可变）
```

| 状态 | 说明 |
| --- | --- |
| `pending` | 排队等待执行 |
| `running` | 执行中 |
| `waiting_approval` | 等待人工确认 |
| `recovering` | 恢复中（故障 / 中断恢复） |
| `succeeded` | 成功（终态） |
| `failed` | 失败（终态，可重试） |
| `canceled` | 已取消（终态，不可重试） |
