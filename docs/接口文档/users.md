# 用户管理模块（Users）

> 前缀：`/api/v1/users` · 代码：`backend/app/api/v1/users.py`

V1 为单用户模式（`user_id` 恒为 1），此处提供用户信息查询、任务列表与统计等基础接口。
多用户版本（V2+）将补充注册、JWT 登录、权限管理。

## 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/users/me` | 获取当前用户信息 |
| GET | `/api/v1/users/me/tasks` | 获取当前用户任务列表（分页 + 筛选） |
| GET | `/api/v1/users/me/stats` | 获取用户统计信息 |

---

## 1. GET /users/me — 当前用户信息

返回固定用户基本信息（单用户模式）。注意：**无 `response_model`，返回普通 dict**。

**响应 200**

```json
{
  "id": 1,
  "email": "user@example.com",
  "is_active": true
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 用户 ID（固定为 1） |
| `email` | string | 邮箱（V1 固定占位值） |
| `is_active` | bool | 是否启用（固定 true） |

---

## 2. GET /users/me/tasks — 我的任务列表

当前用户的任务列表，复用 `TaskService.list`，返回结构与 `GET /tasks` 完全一致（`PaginatedResponse[TaskResponse]`）。

**Query 参数**（`TaskFilterParams`，继承 `PaginationParams`）

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | int | 否 | 页码，默认 1 |
| `page_size` | int | 否 | 每页数量 1–100，默认 20 |
| `status` | string | 否 | 任务状态（pending/running/waiting_approval/recovering/succeeded/failed/canceled） |
| `type` | string | 否 | 任务类型（见 enums.md） |
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

> `progress` 由 `TaskService.update_status` 写入的 `payload["progress"]` 派生（0–100），已修复恒为 0 的问题。任务字段完整说明见 [tasks.md](./tasks.md)。

---

## 3. GET /users/me/stats — 用户统计

汇总当前用户的待处理任务数、活跃会话数、职位总数，供 Dashboard 展示。**返回普通 dict，无 response_model**。

**响应 200**

```json
{
  "pending_tasks": 3,
  "active_conversations": 5,
  "total_jobs": 128
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `pending_tasks` | int | 待处理任务数（`task_service.get_pending_tasks_count`，status=pending） |
| `active_conversations` | int | 活跃会话数（`conversation_repo.count_active`，status=active） |
| `total_jobs` | int | 职位总数（`job_repo.count_by_user`） |
