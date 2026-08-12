// Service Worker：扩展后台中枢。
// 职责：
//   1. 生命周期管理（安装、激活）
//   2. 跨上下文消息路由（sidepanel / content / popup ↔ background）
//   3. 设置变更广播（storage.onChanged → 所有上下文）
//   4. Side Panel 打开控制（点击扩展图标打开 side panel）
//   5. 与后端 WebSocket 通信（Phase 2 接入）
//
// 设计说明：
//   Chrome Extension MV3 的 service worker 是事件驱动的，可能随时被终止。
//   因此不保存长生命周期状态，状态统一在 chrome.storage 中持久化。
//   消息处理函数必须在顶层同步注册（onMessage 监听器），否则 SW 唤醒后无法接收消息。

import { MessageType } from "../types/messages"
import type { RuntimeMessage, ApprovalDecisionPayload } from "../types/messages"
import { loadSettings } from "../lib/storage"

console.info("[background] service worker loaded")

// ---------------------------------------------------------------------------
// 1. 生命周期钩子
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(async (details) => {
  console.info("[background] onInstalled:", details.reason)

  // 首次安装时初始化默认设置（确保 storage 中有值，各上下文读取一致）
  if (details.reason === "install") {
    const existing = await loadSettings()
    if (!existing) {
      // 默认值与 settings store 的 DEFAULT_SETTINGS 保持一致
      // 这里只做"确保存在"，真正的默认值源在 store 中维护
      chrome.storage.local.set({
        app_settings: {
          llmProvider: "doubao",
          apiKey: "",
          apiBaseUrl: "",
          autoReply: false,
          autoApply: false,
          concurrency: 1,
          replyStyle: "polite",
        },
      })
      console.info("[background] default settings initialized")
    }
  }
})

chrome.runtime.onStartup.addListener(() => {
  console.info("[background] browser startup")
})

// ---------------------------------------------------------------------------
// 2. Side Panel 打开（保留 onClicked 备用）
// ---------------------------------------------------------------------------

// 注意：manifest 已设 default_popup，Chrome 规定此时点击图标只弹 popup，
// action.onClicked 不会触发，因此下方 handler 当前为死代码。
// 实际入口：popup/App.vue 的「打开 SidePanel ▸」按钮经用户手势调用 chrome.sidePanel.open()。
// 若未来移除 default_popup，此 handler 即成为「点击图标直接开 SidePanel」的路径。
chrome.action.onClicked.addListener(async (tab) => {
  if (tab?.id !== undefined) {
    try {
      await chrome.sidePanel.open({ tabId: tab.id })
    } catch (err) {
      console.warn("[background] sidePanel.open failed:", err)
    }
  }
})

// ---------------------------------------------------------------------------
// 3. 设置变更广播
// ---------------------------------------------------------------------------
// 当任一侧上下文中修改了设置（写入 storage），所有上下文都会收到 onChanged。
// 但 runtime.onMessage 是更结构化的通信方式，这里做一个桥接：
// storage 变更 → 构造 RuntimeMessage → 广播给所有活跃 tab 的 content script + sidepanel。
//
// 实际上 sidepanel/popup 自己也监听了 storage.onChanged，
// 所以这里主要是为了未来 content script 也能响应设置变更。

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return
  if ("app_settings" in changes) {
    const newSettings = changes.app_settings.newValue
    const message: RuntimeMessage = {
      type: MessageType.SettingsUpdated,
      payload: newSettings,
    }
    // 广播给所有 tab 的 content script
    chrome.tabs.query({}, (tabs) => {
      for (const tab of tabs) {
        if (tab.id !== undefined) {
          chrome.tabs.sendMessage(tab.id, message).catch(() => {
            // 部分 tab 可能没有 content script，忽略即可
          })
        }
      }
    })
  }
})

// ---------------------------------------------------------------------------
// 4. 消息路由（sidepanel / popup / content → background）
// ---------------------------------------------------------------------------
// 统一入口，按 MessageType 分发处理。
// 每条消息必须调用 sendResponse 回复，否则调用方会超时。
//
// TODO(Phase 2):
//   - ApprovalDecided 转发给后端 WebSocket
//   - AgentStatusUpdated 从后端 WebSocket 接收后广播给 sidepanel

chrome.runtime.onMessage.addListener((msg: unknown, _sender, sendResponse) => {
  const message = msg as RuntimeMessage
  if (!message?.type) {
    sendResponse({ ok: false, error: "missing_message_type" })
    return false
  }

  switch (message.type) {
    case MessageType.ApprovalDecided: {
      handleApprovalDecided(message.payload as ApprovalDecisionPayload)
      sendResponse({ ok: true })
      break
    }

    case MessageType.SettingsUpdated: {
      // 设置变更由 storage.onChanged 统一广播，这里只做 ack
      sendResponse({ ok: true })
      break
    }

    default:
      sendResponse({ ok: false, error: "unknown_message_type" })
      break
  }

  // 保持 sendResponse 异步可用（当前都是同步处理，但预留异步扩展位）
  return false
})

// ---------------------------------------------------------------------------
// 消息处理函数
// ---------------------------------------------------------------------------

/**
 * 处理 Approval 决策（用户在 sidepanel 点击同意/拒绝）。
 * Phase 1：仅日志，Phase 2 转发给后端 WebSocket。
 */
function handleApprovalDecided(payload: ApprovalDecisionPayload): void {
  console.info(
    `[background] approval decided: ${payload.approvalId} -> ${payload.decision}`,
  )
  // TODO(Phase 2): 通过 WebSocket 将决策发送给后端
}
