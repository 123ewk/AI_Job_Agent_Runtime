// chrome.storage.local 类型安全包装器。
// 职责：统一管理扩展本地存储，保证各上下文（sidepanel/background/popup）状态同步。
// 原理：chrome.storage 是跨上下文共享的，变更时触发 onChanged 事件。

import type { AppSettings } from "../stores/settings"

const STORAGE_KEYS = {
  SETTINGS: "app_settings",
} as const

/** 浏览器桥 token 的 storage key（用户在 popup 粘贴，由 background bridge 消费）。 */
export const BRIDGE_TOKEN_KEY = "browser_mcp_token"

/** 方案 A：活动配置真源（含明文 api_key，仅本机扩展私有）的 storage key。 */
export const ACTIVE_SETTINGS_KEY = "active_settings"

// 引入类型但延迟 import，避免循环依赖（storage.ts ← settings store 都用到此 key）
import type { ActiveSettings } from "../stores/settings"

/**
 * 读取本地活动配置真源。不存在时返回 null（首启/迁移场景由调用方回退后端）。
 * 用途：设置页开页还原「上次一模一样」（含真实 api_key），并可在建连时重推注册表。
 */
export async function getActiveSettings(): Promise<ActiveSettings | null> {
  const result = await chrome.storage.local.get(ACTIVE_SETTINGS_KEY)
  const raw = result[ACTIVE_SETTINGS_KEY]
  if (!raw) return null
  return raw as ActiveSettings
}

/** 写入本地活动配置真源（设置变更时同步，明文 api_key 仅存本机扩展私有区）。 */
export async function saveActiveSettings(settings: ActiveSettings): Promise<void> {
  await chrome.storage.local.set({ [ACTIVE_SETTINGS_KEY]: settings })
}

/**
 * 读取设置（从 chrome.storage.local）。
 * 不存在时返回 null，由调用方提供默认值。
 */
export async function loadSettings(): Promise<AppSettings | null> {
  const result = await chrome.storage.local.get(STORAGE_KEYS.SETTINGS)
  const raw = result[STORAGE_KEYS.SETTINGS]
  if (!raw) return null
  return raw as AppSettings
}

/**
 * 保存设置（写入 chrome.storage.local）。
 * 写入后会触发 chrome.storage.onChanged，各上下文可监听同步。
 */
export async function saveSettings(settings: AppSettings): Promise<void> {
  await chrome.storage.local.set({ [STORAGE_KEYS.SETTINGS]: settings })
}

/**
 * 监听设置变更（用于跨上下文状态同步）。
 * 返回 unsubscribe 函数。
 */
export function onSettingsChanged(callback: (settings: AppSettings) => void): () => void {
  function listener(
    changes: Record<string, chrome.storage.StorageChange>,
    areaName: string,
  ): void {
    if (areaName !== "local") return
    const change = changes[STORAGE_KEYS.SETTINGS]
    if (change?.newValue) {
      callback(change.newValue as AppSettings)
    }
  }

  chrome.storage.onChanged.addListener(listener)
  return () => chrome.storage.onChanged.removeListener(listener)
}
