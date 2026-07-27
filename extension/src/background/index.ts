// Service Worker：扩展后台。
// 职责：生命周期管理、消息路由、与后端通信（Phase 2 接入 WebSocket）。
// Phase 0 仅搭骨架：onInstalled 钩子 + 消息路由占位。

import { MessageType } from "../types/messages"

console.info("[background] service worker loaded")

chrome.runtime.onInstalled.addListener((details) => {
  console.info("[background] onInstalled:", details.reason)
})

// sidepanel / content -> background 的消息路由
chrome.runtime.onMessage.addListener((msg: unknown, _sender, sendResponse) => {
  const message = msg as { type?: MessageType }
  switch (message.type) {
    case MessageType.ApprovalDecided:
      // TODO: Phase 2 将决策转发给后端
      console.info("[background] approval decided")
      sendResponse({ ok: true })
      break
    default:
      sendResponse({ ok: false, error: "unknown_message_type" })
  }
  return true // 保持 sendResponse 异步可用
})
