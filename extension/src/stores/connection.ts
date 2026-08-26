// 后端连接状态 store（文档 V1.0 §16 连接状态，样式规范 §12）。
// 职责：维护与后端 WS/REST 的连接态（connected/reconnecting/disconnected）与心跳时间。
// 原理：Phase 2 后端 WS 为 stub（记忆 phase2-progress 风险 2），当前以 /api/v1/health REST 探活
//       近似连接态；WS 推送接线后（backend backlog）改为 WS 心跳驱动。
import { defineStore } from "pinia"
import { ref } from "vue"
import { apiGet } from "../lib/api"
import type { WsState } from "../types/components"

export const useConnectionStore = defineStore("connection", () => {
  const state = ref<WsState>("disconnected")
  const lastHeartbeat = ref<string | undefined>(undefined)
  const backendUrl = ref("localhost:8000")

  /**
   * 探活：GET /api/v1/health。成功 → connected；网络/超时/非 2xx → disconnected。
   * UI 展示后端连接状态（文档 §16），不抛错——失败即未连接，由连接点颜色表达。
   */
  async function checkHealth(): Promise<void> {
    try {
      await apiGet<{ status: string }>("/health")
      state.value = "connected"
      lastHeartbeat.value = new Date().toLocaleTimeString()
      // 方案 A：建连即补推活动配置到注册表（后端进程重启后注册表为空，靠此重推）。
      // 运行时引用 settings store，避免顶层循环依赖。
      const { useSettingsStore } = await import("./settings")
      await useSettingsStore().pushActive()
    } catch {
      state.value = "disconnected"
    }
  }

  return { state, lastHeartbeat, backendUrl, checkHealth }
})
