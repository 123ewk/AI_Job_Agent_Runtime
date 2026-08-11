# 职位管理模块（Jobs）

> 前缀：`/api/v1/jobs` · 代码：`backend/app/api/v1/jobs.py` · DTO：`backend/app/schema/job.py`

提供职位列表查询、详情、CRUD 以及 HR 信息管理。所有接口按用户隔离（`user_id` 恒为 1）。
同平台同 `external_id` 自动去重（返回已有记录，不重复创建）。

## 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/jobs` | 获取职位列表（筛选 + 分页） |
| GET | `/api/v1/jobs/{job_id}` | 获取职位详情 |
| POST | `/api/v1/jobs` | 创建职位 |
| PUT | `/api/v1/jobs/{job_id}` | 更新职位 |
| DELETE | `/api/v1/jobs/{job_id}` | 删除职位 |
| GET | `/api/v1/jobs/hr/list` | 获取 HR 列表 |
| POST | `/api/v1/jobs/hr` | 创建 HR |

---

## 1. GET /jobs — 职位列表

**Query 参数**（`JobFilterParams` + `PaginationParams`）

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | int | 否 | 页码，默认 1 |
| `page_size` | int | 否 | 每页数量 1–100，默认 20 |
| `status` | string | 否 | 按状态筛选（见 enums.md `JobStatus`） |
| `platform` | string | 否 | 按平台筛选 |
| `keyword` | string | 否 | 关键词搜索（`title`/`company` ILIKE 模糊匹配） |
| `min_score` | float | 否 | 最低匹配评分（`score >= min_score`） |

> ✅ **已修复**：`keyword` 与 `min_score` 过滤逻辑已实现——`JobRepository.list_with_search`
> 将等值过滤与 `ILIKE`（title/company）+ `>=`（score）组合查询；任一参数传入即走该路径，
> 否则保持原有等值过滤分页。

**响应 200** — `PaginatedResponse[JobResponse]`

```json
{
  "items": [
    {
      "id": 1,
      "user_id": 1,
      "platform": "boss",
      "external_id": "boss_123456",
      "title": "Python 后端工程师",
      "company": "某科技公司",
      "salary": "25K-40K",
      "location": "上海",
      "description": "负责后端服务开发...",
      "source_url": "https://www.zhipin.com/job/123456.html",
      "hr_id": 5,
      "status": "scored",
      "score": 0.85,
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
| `id` | int | 职位 ID |
| `user_id` | int | 用户 ID |
| `platform` | string | 平台标识（默认 boss，≤30） |
| `external_id` | string | 平台侧职位 ID（去重锚点，≤100） |
| `title` | string\|null | 职位名称（≤300） |
| `company` | string\|null | 公司名称（≤200） |
| `salary` | string\|null | 薪资范围（≤100） |
| `location` | string\|null | 工作地点（≤200） |
| `description` | string\|null | 职位描述 |
| `source_url` | string\|null | 职位来源链接（≤500） |
| `hr_id` | int\|null | 关联 HR ID |
| `status` | string | 职位状态（discovered/scored/chatting/applied/rejected/closed/skipped） |
| `score` | float\|null | 匹配评分 |
| `created_at` / `updated_at` | datetime | 创建 / 更新时间 |

---

## 2. GET /jobs/{job_id} — 职位详情

**路径参数**：`job_id`（int）

**响应 200** — `JobResponse`（字段同上）
**错误**：404 `not_found`（职位不存在或非当前用户）

---

## 3. POST /jobs — 创建职位

**请求体** — `JobCreate`

```json
{
  "platform": "boss",
  "external_id": "boss_123456",
  "title": "Python 后端工程师",
  "company": "某科技公司",
  "salary": "25K-40K",
  "location": "上海",
  "description": "负责后端服务开发...",
  "source_url": "https://www.zhipin.com/job/123456.html",
  "hr_id": 5
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `platform` | string | 否（默认 boss） | ≤30 |
| `external_id` | string | **是** | 平台侧职位 ID（去重锚点）≤100 |
| `title` | string\|null | 否 | ≤300 |
| `company` | string\|null | 否 | ≤200 |
| `salary` | string\|null | 否 | ≤100 |
| `location` | string\|null | 否 | ≤200 |
| `description` | string\|null | 否 | - |
| `source_url` | string\|null | 否 | ≤500 |
| `hr_id` | int\|null | 否 | 关联 HR ID |

**响应 201** — `JobResponse`
**去重**：同平台同 `external_id` 已存在时直接返回已有记录（`get_by_platform_external`）。

---

## 4. PUT /jobs/{job_id} — 更新职位

部分更新，仅传需要修改的字段（`exclude_unset=True`）。

**请求体** — `JobUpdate`

```json
{
  "title": "高级 Python 后端工程师",
  "salary": "30K-50K",
  "status": "chatting",
  "score": 0.92
}
```

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `title` / `company` / `salary` / `location` / `source_url` | string\|null | 长度限制同创建 |
| `description` | string\|null | - |
| `status` | string\|null | 职位状态（JobStatus 枚举） |
| `score` | float\|null | 匹配评分 ≥0 |

**响应 200** — `JobResponse`
**错误**：404 `not_found`

---

## 5. DELETE /jobs/{job_id} — 删除职位

**路径参数**：`job_id`（int）。当前为**硬删除**，关联会话不受影响（外键置空）。

**响应 200** — `StatusResponse`

```json
{ "status": "ok", "message": "职位已删除" }
```

**错误**：404 `not_found`

---

## 6. GET /jobs/hr/list — HR 列表

**Query 参数**：`page`（默认 1）、`page_size`（默认 20，1–100）

**响应 200** — `PaginatedResponse[HRResponse]`

```json
{
  "items": [
    {
      "id": 5,
      "user_id": 1,
      "platform": "boss",
      "external_id": "boss_hr_888",
      "name": "王经理",
      "company": "某科技公司",
      "position": "HRBP",
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
| `id` | int | HR ID |
| `user_id` | int | 用户 ID |
| `platform` | string | 平台标识（≤30） |
| `external_id` | string | 平台侧 HR ID（去重锚点，≤100） |
| `name` | string\|null | HR 姓名（≤100） |
| `company` | string\|null | 公司名称（≤200） |
| `position` | string\|null | HR 职位（≤200） |
| `created_at` | datetime | 创建时间 |

---

## 7. POST /jobs/hr — 创建 HR

> 注意：路由注释为"创建或更新"，但 `JobService.create_hr` 实际行为是 **同平台同 `external_id` 已存在时直接返回已有记录，不做更新**。

**请求体** — `HRCreate`

```json
{
  "platform": "boss",
  "external_id": "boss_hr_888",
  "name": "王经理",
  "company": "某科技公司",
  "position": "HRBP"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `platform` | string | 否（默认 boss） | ≤30 |
| `external_id` | string | **是** | 平台侧 HR ID（去重锚点）≤100 |
| `name` | string\|null | 否 | ≤100 |
| `company` | string\|null | 否 | ≤200 |
| `position` | string\|null | 否 | ≤200 |

**响应 201** — `HRResponse`

---

## 职位状态流转（JobStatus）

```
discovered → scored → chatting → applied
                              ↘ rejected
                              ↘ closed
                              ↘ skipped
```

| 状态 | 说明 |
| --- | --- |
| `discovered` | 已发现（同步落库） |
| `scored` | 已匹配评分 |
| `chatting` | 沟通中 |
| `applied` | 已投递 |
| `rejected` | 已被拒 |
| `closed` | 已关闭 |
| `skipped` | 已跳过 |
