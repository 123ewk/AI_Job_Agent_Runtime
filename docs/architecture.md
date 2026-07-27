# Phase 0 骨架架构说明

> 本文记录 Phase 0 已落地的项目骨架结构与数据流。完整设计见
> `docs/AI求职Agent_设计文档_V2.0/` 与 `docs/spec/AI求职Agent开发Spec_V1.1_技术栈冻结版.md`。

## 1. 分层架构（backend/app）

依赖方向严格自上而下，禁止反向调用：

```
api (HTTP/WS 接口层)  →  service (业务逻辑层，Phase 2+ 接入)  →  repository (数据访问层)  →  database
        ↓                         ↓                                ↓
      schemas (DTO)            core (config/logging)           db (engine/session/Base)
```

Phase 0 已实现：

- `core/config.py`：`Settings`（pydantic-settings）从仓库根 `.env` 读取，统一承载所有配置。
- `core/logging.py`：structlog 结构化日志，dev 控制台渲染 / prod JSON 渲染。
- `db/base.py`：async engine（asyncpg）+ `async_session_factory` + `Base` + `TimestampMixin`。
- `models/`：9 张核心表 ORM（SQLAlchemy 2.0 `Mapped` 风格）。
- `api/v1/health.py`：存活 / 就绪探针。
- `api/deps.py`：`get_db`、`get_app_settings` 依赖注入。

## 2. 数据流（运行时目标态）

```
Chrome Extension (SidePanel/Popup/Content)
        ↕ chrome.runtime 消息
Service Worker (background)
        ↕ HTTP / WebSocket
Backend (FastAPI)
        ↕
LangGraph Agent → Skill → MCP Client --stdio--> Chrome MCP Server → Browser
        ↓
PostgreSQL (业务数据 + pgvector 向量) / Redis (Stream 队列 + 缓存) / MinIO (简历/截图/证据)
```

Phase 0 仅打通基础设施与扩展骨架，Agent / Skill / MCP 链路在 Phase 3+ 接入。

## 3. 数据库（9 张核心表）

| 表 | 职责 | 关键字段 |
|---|---|---|
| users | 用户与设置 | email、llm_provider、settings(JSONB) |
| tasks | Agent 任务 | type、status(7 态机)、payload/result(JSONB) |
| conversations | HR 会话 | platform、external_id、uuid |
| messages | 聊天消息 | role、source(manual/agent/history)、external_msg_id |
| jobs | 岗位 | score、score_detail、status |
| resumes | 简历 | content、embedding(Vector 512, bge-small-zh) |
| approvals | 人工确认 | type(6 类敏感)、status、expires_at |
| sync_records | 同步记录 | mode(initial/manual/incremental)、status |
| execution_logs | 执行日志 | node、tool、input/output、latency_ms |

迁移：`alembic/versions/0001_initial_schema.py`，含 `CREATE EXTENSION vector`、外键、Check 约束与索引。

## 4. 扩展结构（extension/src）

- `background/index.ts`：Service Worker，生命周期 + 消息路由。
- `content/index.ts`：页面 DOM 提取与操作。
- `popup/`：工具栏弹窗（Vue3）。
- `sidepanel/`：主交互面板（Vue3），展示 Agent 状态 / Approval / 设置。
- `stores/`：Pinia（agent / settings）。
- `types/messages.ts`：跨上下文消息契约。

## 5. 配置与环境隔离

- `.env.example`（仓库根）：模板，入库。
- `.env`（仓库根，gitignore）：实际值，不入库。backend `Settings` 向上寻址读取，与未来其他服务共享。
- 环境：`dev` → `test` → `staging` → `prod`，通过 `APP_ENV` 切换。

## 6. 已知限制 / 后续

- Agent / Skill / MCP / WebSocket 链路未接入（Phase 2+）。
- Redis Stream 队列、JWT 鉴权、文件上传走 MinIO 的业务逻辑未实现（对应 Phase）。
- pre-commit 的 mypy `--strict` 依赖 backend 虚拟环境，已通过 `uv run --directory backend` 解决。
