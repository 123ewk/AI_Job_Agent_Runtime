// 用户设置 store：对齐 spec Phase 1 Settings。
// 职责：管理全局配置，持久化到 chrome.storage.local，跨上下文同步。
// 原理：chrome.storage 是扩展各上下文共享的唯一持久层；
// onChanged 事件保证 sidepanel / popup / background 状态一致。

import { defineStore } from "pinia"
import { ref } from "vue"
import { loadSettings, saveSettings, onSettingsChanged } from "../lib/storage"

export type LLMProvider = "doubao" | "openai" | "anthropic" | "qwen" | "deepseek"
export type ReplyStyle = "polite" | "professional" | "concise" | "friendly"

export interface AppSettings {
  llmProvider: LLMProvider
  apiKey: string
  apiBaseUrl?: string
  autoReply: boolean
  autoApply: boolean
  concurrency: number
  replyStyle: ReplyStyle
}

const DEFAULT_SETTINGS: AppSettings = {
  llmProvider: "doubao",
  apiKey: "",
  apiBaseUrl: "",
  autoReply: false,
  autoApply: false,
  concurrency: 1,
  replyStyle: "polite",
}

export const useSettingsStore = defineStore("settings", () => {
  const config = ref<AppSettings>({ ...DEFAULT_SETTINGS })
  const initialized = ref<boolean>(false)

  /**
   * 从 chrome.storage.local 加载已有配置。
   * 组件挂载时调用一次，避免默认值覆盖用户设置。
   */
  async function init(): Promise<void> {
    if (initialized.value) return
    const stored = await loadSettings()
    if (stored) {
      config.value = { ...DEFAULT_SETTINGS, ...stored }
    }
    initialized.value = true
  }

  /**
   * 部分更新设置并持久化。
   * 写入 storage 后会触发 onChanged，各上下文自动同步。
   */
  async function update(patch: Partial<AppSettings>): Promise<void> {
    const next = { ...config.value, ...patch }
    // 边界校验：并发数 1-10
    if (next.concurrency < 1) next.concurrency = 1
    if (next.concurrency > 10) next.concurrency = 10
    config.value = next
    await saveSettings(next)
  }

  /**
   * 恢复默认设置。
   */
  async function reset(): Promise<void> {
    config.value = { ...DEFAULT_SETTINGS }
    await saveSettings(config.value)
  }

  /**
   * 订阅跨上下文设置变更。
   * 例如 sidepanel 修改了设置，popup 也要同步更新。
   * 返回 unsubscribe 函数。
   */
  function subscribe(callback: (settings: AppSettings) => void): () => void {
    return onSettingsChanged((newSettings) => {
      // 先更新本地 state，再回调
      config.value = { ...DEFAULT_SETTINGS, ...newSettings }
      callback(config.value)
    })
  }

  return { config, initialized, init, update, reset, subscribe }
})
