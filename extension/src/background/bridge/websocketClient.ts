// 浏览器桥 WebSocket 客户端（Service Worker 独占）。
//
// 职责：
//   1. 连接本机 Chrome MCP Server 的 /ws 端点（127.0.0.1:12307）
//   2. 首条消息带 token 认证（token 由用户在 popup 粘贴，存 chrome.storage.local）
//   3. 24s keepalive alarm 保活（MV3 SW 随时可能被终止，alarm 唤醒后自动重连）
//   4. 把 server 发来的工具请求（id/method/params）路由给 toolsHandler 执行，
//      并回送 { id, result } / { id, error }
//   5. 通过 RuntimeMessage(BridgeStateChanged) 广播连接状态给 popup/sidepanel
//
// 对齐设计：docs/AI求职Agent_设计文档_V2.0/17-ChromeMCPServer落地选型与实现.md
// 注意：本模块在模块顶层同步注册监听器（MV3 约束），并在 index.ts 顶部被 import。

import { MessageType } from "../../types/messages"
import type { BridgeStatePayload } from "../../types/messages"
import { BRIDGE_TOKEN_KEY } from "../../lib/storage"
import { handleToolRequest } from "./toolsHandler"

const WS_URL = "ws://127.0.0.1:12307/ws"
const KEEPALIVE_ALARM = "bridge-keepalive"
const KEEPALIVE_INTERVAL_MIN = 0.4 // ~24s，低于 30s SW 终止窗口

let ws: WebSocket | null = null
let wsToken: string | null = null

function broadcastState(connected: boolean): void {
  const payload: BridgeStatePayload = { connected, hasToken: !!wsToken }
  chrome.runtime.sendMessage({ type: MessageType.BridgeStateChanged, payload }).catch(() => {
    // popup/sidepanel 未打开时无人接收，忽略
  })
}

// --- token ---
async function loadToken(): Promise<string | null> {
  const result = await chrome.storage.local.get(BRIDGE_TOKEN_KEY)
  wsToken = (result[BRIDGE_TOKEN_KEY] as string | undefined) ?? null
  return wsToken
}

// --- WebSocket 生命周期 ---
async function connect(): Promise<void> {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return

  if (wsToken === null) await loadToken()
  if (!wsToken) {
    console.info("[bridge] no token configured — open popup to set one")
    broadcastState(false)
    return
  }

  try {
    ws = new WebSocket(WS_URL)
  } catch (err) {
    console.warn("[bridge] websocket constructor failed:", err)
    ws = null
    return // alarm 会重试
  }

  ws.onopen = () => {
    console.info("[bridge] ws open, authenticating...")
    ws?.send(JSON.stringify({ type: "auth", token: wsToken }))
  }

  ws.onmessage = async (event) => {
    let msg: { type?: string; id?: number; method?: string; params?: unknown }
    try {
      msg = JSON.parse(String(event.data))
    } catch {
      return
    }

    if (msg.type === "auth_ok") {
      console.info("[bridge] authenticated")
      broadcastState(true)
      return
    }

    if (msg.method && msg.id != null) {
      try {
        const result = await handleToolRequest(msg.method, (msg.params as Record<string, unknown>) ?? {})
        ws?.send(JSON.stringify({ id: msg.id, result }))
      } catch (err) {
        ws?.send(JSON.stringify({ id: msg.id, error: err instanceof Error ? err.message : String(err) }))
      }
    }
  }

  ws.onclose = (event) => {
    console.info("[bridge] disconnected:", event.code, event.reason)
    ws = null
    broadcastState(false)
    // alarm 负责重连
  }

  ws.onerror = () => {
    // onclose 随后触发，这里只记录
    console.warn("[bridge] ws error")
  }
}

function disconnect(): void {
  chrome.alarms.clear(KEEPALIVE_ALARM)
  if (ws) {
    ws.close()
    ws = null
  }
  broadcastState(false)
}

// --- keepalive alarm（保活 + 重连） ---
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== KEEPALIVE_ALARM) return
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.info("[bridge] alarm: reconnecting...")
    void connect()
  }
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }))
  }
})

async function startKeepalive(): Promise<void> {
  await loadToken()
  if (!wsToken) {
    console.info("[bridge] no token — skipping auto-connect")
    broadcastState(false)
    return
  }
  chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: KEEPALIVE_INTERVAL_MIN })
  await connect()
}

// --- popup/sidepanel 消息入口（同步注册） ---
chrome.runtime.onMessage.addListener((msg: unknown, _sender, sendResponse) => {
  const message = msg as { type?: string; token?: string }
  switch (message?.type) {
    case "getBridgeState": {
      sendResponse({ connected: ws?.readyState === WebSocket.OPEN, hasToken: !!wsToken })
      break
    }
    case "setBridgeToken": {
      wsToken = message.token ?? null
      chrome.storage.local.set({ [BRIDGE_TOKEN_KEY]: wsToken })
      // 设置后立即尝试连接
      if (wsToken) void startKeepalive()
      sendResponse({ ok: true })
      break
    }
    case "bridgeConnect": {
      void startKeepalive()
      sendResponse({ ok: true })
      break
    }
    case "bridgeDisconnect": {
      disconnect()
      sendResponse({ ok: true })
      break
    }
    default:
      return false // 不属本模块，交由 index.ts 主路由
  }
  return true
})

// --- 自动启动 ---
chrome.runtime.onInstalled.addListener(() => void startKeepalive())
chrome.runtime.onStartup.addListener(() => void startKeepalive())
void startKeepalive()
