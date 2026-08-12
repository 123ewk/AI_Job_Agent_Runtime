// UI store：全局界面状态（Toast 队列）。
// 职责：右上角 Toast 通知（成功绿/错误红/信息主色，2-3s 自动消失，样式规范 §4.2 动作反馈）。
// 生命周期：Toast 入队列后 setTimeout 自动 dismiss；store 为单例，超时定时器由 store 自持。
// 导航状态已移交 vue-router（增量 I4，仅 Dashboard 使用），SidePanel 单列不再需要 activeTab。

import { defineStore } from "pinia"
import { ref } from "vue"
import type { Toast, ToastKind } from "../types/components"

/** 自增序号保证同一毫秒内多个 Toast 的 id 唯一 */
let toastSeq = 0

export const useUiStore = defineStore("ui", () => {
  const toasts = ref<Toast[]>([])

  function pushToast(kind: ToastKind, message: string): void {
    const toast: Toast = { id: `${Date.now()}-${toastSeq++}`, kind, message }
    toasts.value.push(toast)
    // 2-3s 自动消失：约 2.6s 后移除，配合 TransitionGroup 退场动画
    setTimeout(() => dismissToast(toast.id), 2600)
  }

  function dismissToast(id: string): void {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  return { toasts, pushToast, dismissToast }
})
