# 健康检查模块（Health）

> 前缀：`/api/v1/health` · 代码：`backend/app/api/v1/health.py` · DTO：`backend/app/schemas/health.py`

提供存活探针、数据库连通性探测与就绪探针，供容器编排（K8s / Docker Compose）与监控系统判断流量调度。

**关键约定**：健康检查内部捕获异常并返回结构化状态，**探测失败仍返回 HTTP 200 + `status=error`**，保证探针语义稳定、不把依赖故障误判为服务 500。

## 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/health` | 存活探针（liveness）：进程是否在运行（不查依赖） |
| GET | `/api/v1/health/db` | PostgreSQL 连通性探测 |
| GET | `/api/v1/health/ready` | 就绪探针（readiness）：依赖组件是否可用 |

---

## 1. GET /health — 存活探针

进程存活检查，不查依赖，进程在运行即返回 `status=ok`。

**响应 200** — `HealthResponse`

```json
{
  "status": "ok",
  "app": "AI Career Copilot",
  "version": "0.1.0",
  "env": "dev"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | `ok` / `error`（当前实现恒为 `ok`） |
| `app` | string | 服务名（`settings.app_name`） |
| `version` | string | 版本号（`app.__version__`） |
| `env` | string | 运行环境（`settings.app_env`：dev / test / staging / prod） |

---

## 2. GET /health/db — 数据库连通性

向 PostgreSQL 发送 `SELECT 1` 探测（`_ping_postgres`）。探测失败不抛 500，返回 `status=error` + `detail`。

**响应 200** — `ComponentStatus`

```json
{ "status": "ok", "detail": null }
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | `ok` / `error` |
| `detail` | string\|null | 失败时的异常信息（成功为 null） |

---

## 3. GET /health/ready — 就绪探针

聚合各依赖组件的探测结果：所有组件 `ok` 时整体为 `ok`，否则 `error`。

当前仅探测 `postgres`（Redis / MinIO 探测留待对应模块接入后补齐）。

**响应 200** — `ReadinessResponse`

```json
{
  "status": "ok",
  "components": {
    "postgres": { "status": "ok", "detail": null }
  }
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | 整体状态：所有组件 `ok` 时为 `ok`，否则 `error` |
| `components` | object | 组件名 → `ComponentStatus{status, detail}` 映射 |
