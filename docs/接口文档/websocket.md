# 实时推送模块（WebSocket）

> 代码：`backend/app/api/ws.py`

提供任务状态变更、HR 消息通知、审批请求等实时事件推送。前端连接后自动订阅当前用户的所有事件。

## 连接方式

| 端点 | 说明 |
| --- | --- |
| `ws://<host>:8000/ws/tasks/{task_id}?token=xxx` | 任务专属订阅（单个任务的事件） |
| `ws://<host>:8000/ws/user?token=xxx` | 用户级订阅（当前用户所有事件，适合 Dashboard） |

> ⚠️ **认证说明**：V1 单用户模式，`user_id` 服务端硬编码为 `1`（`# TODO: 验证 JWT token`），
> `token` 参数已预留但**暂未校验**。V2+ 接入 JWT 后需传 `Authorization`。

## 心跳协议

| 方向 | 消息 | 说明 |
| --- | --- | --- |
| 客户端 → 服务端 | `{"type": "ping"}` | 客户端周期性发送（注释建议每 30s） |
| 服务端 → 客户端 | `{"type": "pong", "ts": "<UTC ISO 8601>"}` | 心跳响应 |
| - | - | **60s 无心跳服务端主动断开**（`asyncio.wait_for(..., 60.0)`，触发 TimeoutError 后 break） |

## 连接确认

连接建立后，服务端立即推送 `system.connected`：

**`/ws/tasks/{task_id}`**：
```json
{
  "type": "system.connected",
  "event_id": "evt_1744346400_0x7f...",
  "ts": "2026-08-10T10:00:00.000Z",
  "trace_id": "",
  "data": {
    "task_id": 100,
    "status": "connected",
    "server_time": "2026-08-10T10:00:00.000Z"
  }
}
```

**`/ws/user`**：`data` 中为 `user_id` 字段（而非 `task_id`）。

## 消息格式（统一信封）

所有事件推送统一结构（`_build_event`）：

```json
{
  "type": "task.updated",
  "event_id": "evt_1744346400_0x7f...",
  "ts": "2026-08-10T10:00:00.000Z",
  "trace_id": "trace_xxx",
  "data": {
    "task_id": 100,
    "status": "running",
    "progress": 50,
    "message": "正在处理..."
  }
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `type` | string | 事件类型（见下表） |
| `event_id` | string | 事件唯一 ID（`evt_{unix 秒}_{id(data)}`） |
| `ts` | string | 事件时间（UTC ISO 8601） |
| `trace_id` | string | 追踪 ID（当前恒为空串，预留） |
| `data` | object | 事件负载（按类型而异） |

## 事件类型

| type | 触发时机 | `data` 关键字段 |
| --- | --- | --- |
| `system.connected` | 连接建立 | `task_id` / `user_id`、`status`、`server_time` |
| `task.updated` | 任务状态变更 | `task_id`、`status`、`progress`、`message` |
| `task.step` | Agent 执行节点更新 | `task_id`、`node`、`state`、`detail` |
| `message.received` | HR 新消息到达 | `conversation_id`、`message` |
| `approval.required` | 需要人工确认 | `approval_id`、`task_id`、`expires_at` |
| `sync.progress` | 同步进度更新 | `sync_record_id`、`synced`、`total`、`progress` |
| `monitor.state` | 监听状态变更 | （预留，无发送实现） |
| `log.appended` | 关键日志追加 | `task_id`、`level`、`node`、`message` |

## 事件示例

### task.updated（任务状态变更）

```json
{
  "type": "task.updated",
  "event_id": "evt_...",
  "ts": "2026-08-10T10:00:00Z",
  "trace_id": "",
  "data": {
    "task_id": 100,
    "status": "succeeded",
    "progress": 100,
    "message": "执行完成"
  }
}
```

### task.step（执行节点更新）

```json
{
  "type": "task.step",
  "event_id": "evt_...",
  "ts": "2026-08-10T10:00:00Z",
  "trace_id": "",
  "data": {
    "task_id": 100,
    "node": "generate_reply",
    "state": "running",
    "detail": "生成回复草稿"
  }
}
```

### approval.required（人工确认请求）

```json
{
  "type": "approval.required",
  "event_id": "evt_...",
  "ts": "2026-08-10T10:00:00Z",
  "trace_id": "",
  "data": {
    "approval_id": 1,
    "task_id": 100,
    "expires_at": "2026-08-10T10:00:20Z"
  }
}
```

### message.received（HR 新消息）

```json
{
  "type": "message.received",
  "event_id": "evt_...",
  "ts": "2026-08-10T10:00:00Z",
  "trace_id": "",
  "data": {
    "conversation_id": 10,
    "message": {
      "id": 3,
      "role": "hr",
      "content": "方便约个时间面试吗？"
    }
  }
}
```

### sync.progress（同步进度）

```json
{
  "type": "sync.progress",
  "event_id": "evt_...",
  "ts": "2026-08-10T10:00:00Z",
  "trace_id": "",
  "data": {
    "sync_record_id": 2,
    "synced": 45,
    "total": 100,
    "progress": 0.45
  }
}
```

### log.appended（关键日志）

```json
{
  "type": "log.appended",
  "event_id": "evt_...",
  "ts": "2026-08-10T10:00:00Z",
  "trace_id": "",
  "data": {
    "task_id": 100,
    "level": "info",
    "node": "fetch_messages",
    "message": "抓取到 5 条新消息"
  }
}
```

## 客户端消息（服务端接收）

| type | 说明 |
| --- | --- |
| `ping` | 心跳，服务端响应 `pong` |
| `subscribe` | 订阅其他任务（`{"type":"subscribe","task_id":123}`）。**当前仅记录日志，未实现多任务订阅** |

## 服务端发送入口

`backend/app/api/ws.py` 暴露的异步发射函数（Service 层调用）：

| 函数 | 对应事件 | 发送范围 |
| --- | --- | --- |
| `emit_task_updated(task_id, user_id, data)` | `task.updated` | 任务连接 + 用户连接 |
| `emit_task_step(task_id, user_id, node, state, detail)` | `task.step` | 任务连接 + 用户连接 |
| `emit_approval_required(approval_id, task_id, user_id, expires_at)` | `approval.required` | 任务连接 + 用户连接 |
| `emit_message_received(conversation_id, user_id, message)` | `message.received` | 仅用户连接 |
| `emit_sync_progress(user_id, sync_record_id, synced, total)` | `sync.progress` | 仅用户连接 |
| `emit_log_appended(task_id, user_id, level, node, msg)` | `log.appended` | 任务连接 + 用户连接 |

> ⚠️ **已知问题**：上述 `emit_*` 函数已定义，但 Service 层**尚未接线**（如 `TaskService.update_status` 中
> `# TODO: WebSocket 推送状态变更事件`）。当前实际运行时**不会**因任务状态变更自动推送事件，需待后续实现接入。
