// Agent 状态 store：Dashboard/SidePanel 展示 Agent 运行状态、当前任务与待确认项。
// 职责：status（运行态）+ monitoring（监听态）+ currentTask（展示文案）+ pendingApprovals。
// 状态驱动：文档 V1.0 §51 —— 前端不自行猜测状态，由 WS/API 消息驱动（当前后端 WS 为 stub，
//           monitoring/currentTask 待 backend 接线，此处仅提供类型化 setter）。
import { defineStore } from "pinia"
import { computed, ref } from "vue"
import type { AgentState, AgentStatusPayload, ApprovalPayload } from "../types/messages"
import type { MonitoringState, StatusValue } from "../types/components"

export const useAgentStore = defineStore("agent", () => {
  const state = ref<AgentState>("idle")
  const taskId = ref<string | undefined>(undefined)
  const currentNode = ref<string | undefined>(undefined)
  const pendingApprovals = ref<ApprovalPayload[]>([])

  // 监听态（monitoring_state：idle/monitoring/paused/stopped）
  const monitoring = ref<MonitoringState>("idle")
  // 当前任务展示文案（如「监听中（boss.com）」）；null 表示无任务
  const currentTask = ref<string | null>(null)

  /**
   * 展示用统一状态（总览主卡/Header badge 消费）。
   * 线格式 AgentState（messages.ts）显式映射到 UI StatusValue（components.ts）：
   *   waiting_hr → waiting_human、completed → done（StatusValue 无对应值）。
   */
  const uiStatus = computed<StatusValue>(() => {
    if (monitoring.value === "monitoring") return "monitoring"
    switch (state.value) {
      case "idle":
        return "idle"
      case "running":
        return "running"
      case "waiting_approval":
        return "waiting_approval"
      case "waiting_hr":
        return "waiting_human"
      case "completed":
        return "done"
      case "failed":
        return "failed"
    }
  })

  function updateStatus(payload: AgentStatusPayload): void {
    state.value = payload.state
    taskId.value = payload.taskId
    currentNode.value = payload.node
  }

  function setMonitoring(next: MonitoringState): void {
    monitoring.value = next
  }

  function setCurrentTask(text: string | null): void {
    currentTask.value = text
  }

  function pushApproval(payload: ApprovalPayload): void {
    pendingApprovals.value.push(payload)
  }

  function resolveApproval(approvalId: string): void {
    pendingApprovals.value = pendingApprovals.value.filter((a) => a.approvalId !== approvalId)
  }

  return {
    state,
    taskId,
    currentNode,
    monitoring,
    currentTask,
    pendingApprovals,
    uiStatus,
    updateStatus,
    setMonitoring,
    setCurrentTask,
    pushApproval,
    resolveApproval,
  }
})
