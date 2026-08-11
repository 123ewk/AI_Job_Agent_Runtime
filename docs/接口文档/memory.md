# 记忆管理模块（Memory）

> 前缀：`/api/v1/memory` · 代码：`backend/app/api/v1/memory.py` · DTO：`backend/app/schema/memory.py`

记忆是 Agent 的长期上下文。检索采用 pgvector 余弦相似度（`similarity_score = 1 - cosine_distance`，0~1，越大越相似）。

**三级加权检索**（仅 `/memory/context/for-task` 使用，权重定义于 `MemoryService`）：
- `conversation`：权重 1.0（当前会话）
- `job`：权重 0.7（关联岗位）
- `global`：权重 0.4（全局偏好）

**去重阈值**：`SIMILARITY_DUPLICATE_THRESHOLD = 0.95`，仅用于「写入时防重复」（见接口 2）。

> ⚠️ **当前 embedding 为 stub**：`_generate_embedding` 返回 512 维零向量（未接入真实 embedding 模型），
> 因此相似度检索在语义上暂不可用。

## 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/memory/search` | 语义检索记忆 |
| POST | `/api/v1/memory` | 添加新记忆 |
| GET | `/api/v1/memory/conversation/{conversation_id}` | 获取会话关联记忆 |
| GET | `/api/v1/memory/job/{job_id}` | 获取岗位关联记忆 |
| DELETE | `/api/v1/memory/{memory_id}` | 删除记忆 |
| POST | `/api/v1/memory/context/for-task/{task_id}` | 获取任务执行所需记忆上下文 |
| POST | `/api/v1/memory/extract` | 从会话历史提取新记忆（stub） |

---

## 1. POST /memory/search — 语义检索记忆

对 query 生成 embedding，做一次 pgvector Top-K 检索（支持元数据过滤），按相似度降序返回。

> 注意：路由 docstring 声称"三级检索合并去重"，**实际 `MemoryService.search` 只做单次检索**，无三级加权合并。

**请求体** — `MemorySearchRequest`

```json
{
  "query": "候选人期望薪资是多少",
  "top_k": 10,
  "conversation_id": 10,
  "job_id": 1,
  "memory_type": "preference"
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query` | string | **是** | 检索查询文本（≥1 字符） |
| `top_k` | int | 否（默认 10） | 返回结果数量 1–50 |
| `conversation_id` | int\|null | 否 | 限定会话上下文 |
| `job_id` | int\|null | 否 | 限定职位上下文 |
| `memory_type` | string\|null | 否 | 按类型筛选（见 enums.md `MemoryType`） |

**响应 200** — `list[MemoryResponse]`

```json
[
  {
    "id": 1,
    "user_id": 1,
    "type": "preference",
    "content": "候选人期望月薪 25K 以上",
    "conversation_id": 10,
    "job_id": null,
    "similarity_score": 0.93,
    "created_at": "2026-08-10T10:00:00Z"
  }
]
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 记忆 ID |
| `user_id` | int | 用户 ID |
| `type` | string | 记忆类型（见下） |
| `content` | string | 记忆内容 |
| `conversation_id` / `job_id` | int\|null | 关联会话 / 职位 |
| `similarity_score` | float\|null | 相似度得分（**仅检索时返回**） |
| `created_at` | string | 创建时间 |

---

## 2. POST /memory — 添加新记忆

对内容生成 embedding 后做去重检查：若检索到相似度 ≥0.95 的已有记忆，**跳过写入，直接返回已有记忆**；否则写入新记忆。

**请求体** — `MemoryCreate`

```json
{
  "type": "fact",
  "content": "HR 要求下周内确认到岗时间",
  "conversation_id": 10,
  "job_id": 1
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `type` | string | **是** | 记忆类型 |
| `content` | string | **是** | 记忆内容 |
| `conversation_id` / `job_id` | int\|null | 否 | 关联会话 / 职位 |

**响应 201** — `MemoryResponse`（去重命中时返回已有记忆，含 `similarity_score`）

---

## 3. GET /memory/conversation/{conversation_id} — 会话记忆

获取某会话关联的记忆列表（无语义排序，按创建时间倒序；仅返回当前用户记忆）。

**Query 参数**：`limit`（int，默认 50）
**响应 200** — `list[MemoryResponse]`

---

## 4. GET /memory/job/{job_id} — 岗位记忆

获取某岗位关联的记忆列表（无语义排序，按创建时间倒序；仅返回当前用户记忆）。

**Query 参数**：`limit`（int，默认 50）
**响应 200** — `list[MemoryResponse]`

---

## 5. DELETE /memory/{memory_id} — 删除记忆

当前为**硬删除**，V2 可实现软删除保留审计记录。

**响应 200** — `StatusResponse`

```json
{ "status": "ok", "message": "记忆已删除" }
```

**错误**：404 `not_found`（记忆不存在）、403 `forbidden`（记忆不属于当前用户）

---

## 6. POST /memory/context/for-task/{task_id} — 任务记忆上下文

从任务解析出 `conversation_id` / `job_id`，再按**三级加权策略**检索（`get_context_for_task`，`top_k=20`）：
并行检索 conversation / job / global 三级，去重（同 content 保留最高加权相似度版本）后按加权相似度降序取 Top-N。

**路径参数**：`task_id`（int）

**响应 200** — 普通 dict。`memories` 元素结构**不是** `MemoryResponse`，而是：

```json
{
  "count": 3,
  "memories": [
    {
      "id": 1,
      "type": "fact",
      "content": "HR 要求下周内确认到岗时间",
      "source": "conversation",
      "raw_similarity": 0.91,
      "weighted_similarity": 0.91,
      "weight": 1.0
    }
  ],
  "levels": {
    "conversation": 1,
    "job": 1,
    "global": 1
  }
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `count` | int | 返回记忆总数 |
| `memories` | array | 记忆列表 |
| `memories[].id` | int | 记忆 ID |
| `memories[].type` | string | 记忆类型 |
| `memories[].content` | string | 记忆内容 |
| `memories[].source` | string | 来源级别：`conversation` / `job` / `global` |
| `memories[].raw_similarity` | float | 原始余弦相似度（0~1） |
| `memories[].weighted_similarity` | float | 加权相似度 = raw × weight |
| `memories[].weight` | float | 该级别权重（1.0 / 0.7 / 0.4） |
| `levels` | object | 各层级命中数（按 `source` 统计）：conversation / job / global |

**错误**：404 `not_found`（任务不存在时 `conversation_id`/`job_id` 为 null，仅检索 global 级，不报错）

---

## 7. POST /memory/extract — 提取新记忆

LLM 分析会话历史，提取事实性信息与用户偏好，去重后写入记忆库（供任务完成后自动调用）。

**Query 参数**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | int | **是** | 待分析的会话 ID |

> ⚠️ **当前为 stub**：`service.extract_and_save` 始终返回 0（不实际提取），`job_id` 与 `messages` 参数在此入口以空值占位。

**响应 200** — `StatusResponse`

```json
{ "status": "ok", "message": "提取完成，新增 0 条记忆" }
```

---

## 记忆类型（MemoryType）

| type | 说明 |
| --- | --- |
| `preference` | 用户偏好（语气、风格、薪资要求等） |
| `hr_pact` | HR 潜规则约定 |
| `interview` | 面试经验总结 |
| `decision` | 决策记录 |
| `fact` | 客观事实信息 |

> 注意：schema 注释中的 `history` **不在枚举内**，传入会被 422 拒绝。
