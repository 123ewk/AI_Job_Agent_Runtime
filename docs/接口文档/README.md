# AI 求职 Agent 后端接口文档

> 版本：V1（Phase 2）· 基准代码：`backend/app/api` · 更新日期：2026-08-10
>
> 本文档全部内容以**真实代码**为准生成，不参考 `docs/spec` 设计文档。权威来源：
> - 路由：`backend/app/api/v1/*.py`、`backend/app/api/ws.py`
> - DTO：`backend/app/schema/*.py`、`backend/app/schemas/*.py`
> - 业务行为：`backend/app/service/*.py`
>
> 代码变更时请同步更新本文档。

## 1. 服务信息

| 项 | 值 |
| --- | --- |
| 服务名 | `AI Career Copilot`（`settings.app_name`，可在 `.env` 覆盖） |
| 应用入口 | `backend/app/main.py`（`create_app()`） |
| 基础路径 | `http://<host>:8000/api/v1` |
| 根路径 | `GET /` → `{"app", "version", "docs"}` |
| 本地启动 | `uv run uvicorn app.main:app --reload --port 8000` |
| OpenAPI | `/docs`（Swagger UI）、`/openapi.json` |
| 健康检查 | `/api/v1/health` |
| WebSocket | `/ws/tasks/{task_id}`、`/ws/user` |

## 2. 模块索引

| # | 模块 | 前缀 | 文档 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | 健康检查 | `/api/v1/health` | [health.md](./health.md) | 存活 / 数据库 / 就绪探针 |
| 2 | 用户管理 | `/api/v1/users` | [users.md](./users.md) | 当前用户信息、任务、统计 |
| 3 | 系统配置 | `/api/v1/settings` | [settings.md](./settings.md) | LLM / Agent / 求职规则 / 回复风格 |
| 4 | 职位管理 | `/api/v1/jobs` | [jobs.md](./jobs.md) | 职位 CRUD + HR 管理 |
| 5 | 会话管理 | `/api/v1/conversations` | [conversations.md](./conversations.md) | 会话 + 消息 + 同步 |
| 6 | 任务管理 | `/api/v1/tasks` | [tasks.md](./tasks.md) | 任务 CRUD + 审批 + 队列统计 |
| 7 | 记忆管理 | `/api/v1/memory` | [memory.md](./memory.md) | 记忆检索 / 写入 / 上下文组装 |
| 8 | 实时推送 | `ws://host/ws/*` | [websocket.md](./websocket.md) | 任务 / 消息 / 审批事件推送 |
| - | 枚举常量 | - | [enums.md](./enums.md) | 状态 / 类型枚举定义 |

## 3. 通用约定

### 3.1 认证方式

**V1 为单用户模式**，不校验 JWT。

- `get_current_user_id()`（`app/api/deps.py`）固定返回 `1`，所有请求默认归属用户 1。
- 请求头无需携带 Token。
- WebSocket 的 `token` 参数已预留但**暂未校验**，`user_id` 服务端硬编码为 1。
- V2+ 计划接入 JWT，届时本约定变更。

### 3.2 请求格式

- `Content-Type: application/json`（POST / PUT 接口）。
- Query 参数用于分页与筛选（列表接口）。
- 路径参数用于资源定位，`{id}` 均为整数。

### 3.3 分页约定

所有列表接口返回统一的 `PaginatedResponse` 包装（`app/schema/common.py`）：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | int | 否 | 页码，从 1 开始，默认 1（`ge=1`） |
| `page_size` | int | 否 | 每页数量，**1–100，默认 20**（`ge=1, le=100`） |

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "total_pages": 0
}
```

`total_pages` 由后端自动计算（`(total + page_size - 1) // page_size`），无需前端传参。

### 3.4 错误响应

除参数校验错误外，**所有异常统一返回 `ErrorResponse`**（`app/schema/common.py`），由 `app/main.py` 全局异常处理器转换：

```json
{
  "error": "not_found",
  "message": "职位不存在",
  "details": {},
  "request_id": null
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `error` | string | 机器可读错误标识（见下表） |
| `message` | string | 用户可读错误信息 |
| `details` | object\|null | 附加错误信息（可选，序列化时 `exclude_none=True`，缺省不下发） |
| `request_id` | string\|null | 请求追踪 ID（可选，缺省不下发） |

### 3.5 错误码对照

| HTTP | `error` | 触发场景 |
| --- | --- | --- |
| 400 | `bad_request` | 请求非法（`BadRequestError`），如批量配置不支持的分类 |
| 403 | `forbidden` | 归属校验失败 / 权限不足（`ForbiddenError`），如删除他人记忆 |
| 404 | `not_found` | 资源不存在（`NotFoundError`），含「非当前用户资源」（V1 不泄露存在性） |
| 409 | `conflict` | 状态冲突（`ConflictError`）：并发会话数超限、状态机非法流转、任务达到最大重试次数等 |
| 4xx/5xx | `http_error` | Starlette HTTP 异常（含 404 路由未匹配） |
| 422 | - | **参数/请求体验证失败，保留 FastAPI 默认 `{"detail": [...]}` 契约，不走 ErrorResponse** |
| 500 | `internal_error` | 未捕获异常兜底（完整堆栈仅记日志，对外只暴露通用信息） |

领域异常继承关系（`app/core/exceptions.py`）：`AppError` 为唯一基类，携带 `status_code` 与 `code`；`NotFoundError` / `ForbiddenError` / `ConflictError` / `BadRequestError` 为其子类。

### 3.6 字段规范

- **未知字段禁止传入**：`BaseSchema` 配置 `extra="forbid"`，请求体带未定义字段直接 422。
- **敏感字段掩码**：LLM 配置接口与 `GET /settings` 列表接口的 `api_key` 均返回掩码（仅首尾 4 字符），存储侧为对称加密（见 [settings.md](./settings.md)）。
- **时间字段**：统一为 ISO 8601 字符串（如 `2026-08-10T12:00:00Z`）。

## 4. 环境与部署

| 环境 | 说明 |
| --- | --- |
| dev | 本地开发，`is_dev=True`，自动放行 `localhost:5173/5174` CORS（`_build_cors_origins`） |
| test / staging / prod | 通过 `.env` 的 `APP_ENV` 切换，配置严格隔离 |

配置由仓库根目录 `.env` 统一管理（`Settings` 向上寻址读取），字段见根目录 `.env.example`。

## 5. 文档维护约定

- 每个模块一个 `.md`，按「接口列表 → 逐接口（路径 / 请求 / 响应 / 错误）→ 状态流转」组织。
- 枚举值以 `app/schema/enums.py` 与 schema 内联校验为准。
- 接口文档与设计文档冲突时**以代码为准**并及时修正本文档。
- 已知实现缺陷（TODO / stub / 与注释不符）在各模块文档「已知问题」小节如实标注。
