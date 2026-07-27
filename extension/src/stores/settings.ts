// 用户设置 store：对齐 spec Phase 1 Settings（LLM / API Key / 自动回复 / 自动投递 / 并发 / 回复风格）。

import { defineStore } from "pinia"
import { ref } from "vue"

export interface AppSettings {
  llmProvider: string
  apiKey: string
  autoReply: boolean
  autoApply: boolean
  concurrency: number
  replyStyle: string
}

export const useSettingsStore = defineStore("settings", () => {
  const config = ref<AppSettings>({
    llmProvider: "doubao",
    apiKey: "",
    autoReply: false,
    autoApply: false,
    concurrency: 1,
    replyStyle: "polite",
  })

  function update(patch: Partial<AppSettings>): void {
    config.value = { ...config.value, ...patch }
  }

  return { config, update }
})
