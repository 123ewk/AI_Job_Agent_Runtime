// Agent 状态 store：SidePanel 展示 Agent 运行状态与待确认项。

import { defineStore } from "pinia"
import { ref } from "vue"
import type { AgentState, AgentStatusPayload, ApprovalPayload } from "../types/messages"

export const useAgentStore = defineStore("agent", () => {
  const state = ref<AgentState>("idle")
  const taskId = ref<string | undefined>(undefined)
  const currentNode = ref<string | undefined>(undefined)
  const pendingApprovals = ref<ApprovalPayload[]>([])

  function updateStatus(payload: AgentStatusPayload): void {
    state.value = payload.state
    taskId.value = payload.taskId
    currentNode.value = payload.node
  }

  function pushApproval(payload: ApprovalPayload): void {
    pendingApprovals.value.push(payload)
  }

  function resolveApproval(approvalId: string): void {
    pendingApprovals.value = pendingApprovals.value.filter((a) => a.approvalId !== approvalId)
  }

  return { state, taskId, currentNode, pendingApprovals, updateStatus, pushApproval, resolveApproval }
})
