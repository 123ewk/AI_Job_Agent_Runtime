// UI store：全局界面状态（活跃 Tab + Toast 队列）。
// 职责：SidePanel Tab 切换、右上角 Toast 通知（成功绿/错误红/信息主色，2-3s 自动消失，doc 12 §4.2）。
// 生命周期：Toast 入队列后 setTimeout 自动 dismiss（doc 12 §10）；store 为单例，超时定时器由 store 自持。

import { defineStore } from "pinia"
import { ref } from "vue"
import type { TabId, Toast, ToastKind } from "../types/components"

/** 自增序号保证同一毫秒内多个 Toast 的 id 唯一 */
let toastSeq = 0

export const useUiStore = defineStore("ui", () => {
  /** 当前活跃 Tab（默认停"状态"，doc 12 §18 窄面板默认） */
  const activeTab = ref<TabId>("status")
  const toasts = ref<Toast[]>([])

  function setTab(tab: TabId): void {
    activeTab.value = tab
  }

  function pushToast(kind: ToastKind, message: string): void {
    const toast: Toast = { id: `${Date.now()}-${toastSeq++}`, kind, message }
    toasts.value.push(toast)
    // 2-3s 自动消失：约 2.6s 后移除，配合 TransitionGroup 退场动画
    setTimeout(() => dismissToast(toast.id), 2600)
  }

  function dismissToast(id: string): void {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  return { activeTab, toasts, setTab, pushToast, dismissToast }
})
