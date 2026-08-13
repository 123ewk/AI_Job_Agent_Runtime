// 事件/日志 store（设计权威：前端布局 V1.0 §22/§52，样式规范 §24-§26）。
// 职责：维护与后端 /ws/user 的 WebSocket 连接，把实时事件追加为时间线日志（上限 200）。
// 后端契约（backend/app/api/ws.py）：消息 {type, event_id, ts, trace_id, data}；
//   心跳客户端每 30s 发 {"type":"ping"}；事件类型 task.updated/task.step/message.received/
//   approval.required/sync.progress/monitor.state/log.appended/system.connected。
// 已知缺口：后端 emit_* 目前为 stub，实际仅连接成功收到 system.connected；
//   本 store 的事件流接线后，LogsView 时间线与 Overview 实时事件模块即可实时驱动。
import { defineStore } from "pinia"
import { ref } from "vue"
import type { WsState } from "../types/components"
import { useConnectionStore } from "./connection"

/** 前端消费的事件日志项（由 WS 事件映射，文档 §52） */
export interface EventLogItem {
  id: string
  /** 后端事件类型（小写点分）：task.updated / log.appended / ... */
  eventType: string
  /** ISO 时间串 */
  ts: string
  traceId: string
  taskId: number | null
  conversationId: number | null
  title: string
  description: string
  /** 展示等级（样式规范 §26 色点）：danger / warning / info / success / muted */
  level: "danger" | "warning" | "info" | "success" | "muted"
  /** 原始 data，高级模式展示 */
  raw: Record<string, unknown>
}

const MAX_EVENTS = 200
const HEARTBEAT_MS = 30_000
const RECONNECT_MS = 5_000
const MAX_RECONNECT = 5

/** 事件类型 → 中文标题（零信任兜底原值） */
const EVENT_TITLES: Record<string, string> = {
  "task.updated": "任务更新",
  "task.step": "执行步骤",
  "message.received": "收到HR消息",
  "approval.required": "需要人工确认",
  "sync.progress": "同步进度",
  "monitor.state": "监听状态变更",
  "log.appended": "日志追加",
  "system.connected": "已连接后端",
}

/** 事件 → 等级色（从事件类型 + data 推导；未知回退 muted） */
function resolveLevel(type: string, data: Record<string, unknown>): EventLogItem["level"] {
  if (type === "approval.required") return "warning"
  if (type === "log.appended" && data.level === "error") return "danger"
  if (type === "task.updated" && (data.status === "failed" || data.status === "canceled")) return "danger"
  if (type === "system.connected") return "success"
  if (type === "task.updated" || type === "task.step" || type === "sync.progress") return "info"
  return "muted"
}

/** 尽力从 data 提取可读描述（message/detail/status/node/content...），兜底 JSON */
function extractDescription(data: Record<string, unknown>): string {
  const candidates = ["message", "detail", "status", "node", "content", "level"]
  for (const key of candidates) {
    const v = data[key]
    if (typeof v === "string" && v) return v
  }
  // message.received 的嵌套 message.content
  const nested = data.message
  if (nested && typeof nested === "object") {
    const content = (nested as Record<string, unknown>).content
    if (typeof content === "string" && content) return content
  }
  return JSON.stringify(data)
}

function numOrNull(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null
}

export const useEventStore = defineStore("events", () => {
  const events = ref<EventLogItem[]>([])
  const wsState = ref<WsState>("disconnected")

  let ws: WebSocket | null = null
  let heartbeatTimer: number | undefined
  let reconnectTimer: number | undefined
  let reconnectAttempts = 0

  function resetTimers(): void {
    if (heartbeatTimer !== undefined) clearInterval(heartbeatTimer)
    heartbeatTimer = undefined
    if (reconnectTimer !== undefined) clearTimeout(reconnectTimer)
    reconnectTimer = undefined
  }

  function append(item: EventLogItem): void {
    events.value = [item, ...events.value].slice(0, MAX_EVENTS)
  }

  /** 解析 WS 消息并追加为日志项（非对象消息直接忽略，防御脏数据） */
  function handleMessage(raw: unknown): void {
    if (typeof raw !== "object" || raw === null) return
    const msg = raw as Record<string, unknown>
    const eventType = typeof msg.type === "string" ? msg.type : "unknown"
    const data = (msg.data && typeof msg.data === "object" ? msg.data : {}) as Record<string, unknown>
    const ts = typeof msg.ts === "string" ? msg.ts : new Date().toISOString()
    append({
      id: typeof msg.event_id === "string" ? msg.event_id : `evt_${events.value.length}_${Date.now()}`,
      eventType,
      ts,
      traceId: typeof msg.trace_id === "string" ? msg.trace_id : "",
      taskId: numOrNull(data.task_id),
      conversationId: numOrNull(data.conversation_id),
      title: EVENT_TITLES[eventType] ?? eventType,
      description: extractDescription(data),
      level: resolveLevel(eventType, data),
      raw: data,
    })
  }

  /**
   * 建立 WS 连接 + 30s 心跳；断线后最多自动重连 5 次（5s 间隔），
   * 超过后置为 disconnected，由用户点「连接」手动恢复。
   */
  function connect(): void {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
    const connection = useConnectionStore()
    // 建立连接期间统一显示 reconnecting；成功后转 connected，失败超限后转 disconnected
    wsState.value = "reconnecting"
    ws = new WebSocket(`ws://${connection.backendUrl}/ws/user`)

    ws.onopen = () => {
      wsState.value = "connected"
      reconnectAttempts = 0
      heartbeatTimer = window.setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }))
      }, HEARTBEAT_MS)
    }
    ws.onmessage = (e) => handleMessage(e.data)
    ws.onerror = () => {
      /* 连接错误统一由 onclose 处理，避免重复走恢复逻辑 */
    }
    ws.onclose = () => {
      resetTimers()
      ws = null
      wsState.value = "disconnected"
      if (reconnectAttempts < MAX_RECONNECT) {
        reconnectAttempts += 1
        wsState.value = "reconnecting"
        reconnectTimer = window.setTimeout(() => {
          reconnectTimer = undefined
          connect()
        }, RECONNECT_MS)
      }
    }
  }

  /** 主动断开（Dashboard 卸载时）；同时抑制后续自动重连 */
  function disconnect(): void {
    reconnectAttempts = MAX_RECONNECT
    resetTimers()
    if (ws) {
      const closing = ws
      ws = null
      closing.close()
    }
    wsState.value = "disconnected"
  }

  function clear(): void {
    events.value = []
  }

  return { events, wsState, connect, disconnect, clear }
})
