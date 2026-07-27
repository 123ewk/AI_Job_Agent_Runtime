# AI 求职 Agent Runtime

垂直领域求职 Agent：岗位发现 → 分析 → HR 沟通 → 自动回复 → 简历投递 → 流程管理。

技术栈（已冻结，详见 `docs/spec/AI求职Agent开发Spec_V1.1_技术栈冻结版.md`）：
Chrome Extension MV3 (Vue3 + TS + Pinia) · FastAPI · LangGraph · LangChain · MCP stdio ·
PostgreSQL + pgvector · Redis Stream · WebSocket · MinIO。

## 仓库结构（Monorepo）

```
AI_Job_Agent_Runtime/
├── backend/            # Python FastAPI 后端（uv 管理）
│   ├── app/            # 应用包：分层架构 core / db / models / api / schemas
│   ├── alembic/        # 数据库迁移
│   ├── scripts/        # 自检脚本
│   ├── tests/
│   ├── pyproject.toml
│   └── .python-version
├── extension/          # Chrome 扩展（Vue3 + Vite + crxjs）
│   └── src/            # background / content / popup / sidepanel / stores / types
├── docker-compose.yml  # 本地基础设施（PG/Redis/MinIO）
├── docs/               # 设计文档与架构说明
├── .env.example        # 环境变量模板
└── CLAUDE.md           # AI 协作开发规则
```

## 前置条件

- Python 3.12+（通过 [uv](https://docs.astral.sh/uv/) 管理）
- Node.js 18+ 与 pnpm 8+
- Docker 与 Docker Compose（用于本地 PG / Redis / MinIO）

## 快速开始

### 1. 准备环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填入 LLM API Key；本地基础设施默认值已可用
```

### 2. 启动基础设施

```bash
docker compose up -d
# 含 PostgreSQL(pgvector) / Redis / MinIO，并自动创建 MinIO bucket
# 注意：在仓库根目录执行，compose 会自动读取根目录的 .env，
# 确保容器凭证与 backend 应用读取的 .env 一致。
```

### 3. 启动后端

```bash
cd backend
uv sync                       # 安装依赖（含 dev 工具）
uv run alembic upgrade head   # 应用数据库迁移（9 张核心表 + pgvector）
uv run uvicorn app.main:app --reload --port 8000
```

验证：

```bash
curl http://localhost:8000/api/v1/health
uv run python scripts/check_services.py   # 探测 PG/Redis/MinIO
```

### 4. 启动扩展

```bash
cd extension
pnpm install
pnpm dev          # vite + crxjs 构建并监听
```

在 Chrome 打开 `chrome://extensions` → 开启开发者模式 → 加载已解压的扩展程序 → 选择 `extension/dist`。

## 测试与质量

```bash
cd backend
uv run pytest                              # 单元测试
uv run ruff check . && uv run ruff format .  # lint + 格式化
uv run mypy app                            # 类型检查

# 仓库根目录
pre-commit install
pre-commit run --all-files
```

## 文档

- 设计文档：`docs/AI求职Agent_设计文档_V2.0/`
- 技术栈与 Spec：`docs/spec/`、`docs/AI求职Agent技术栈与技术选型文档_V1.0.md`
- 骨架架构：`docs/architecture.md`
