// 各上下文（service worker / content script / sidepanel / popup）之间的消息契约。
// 新增消息类型时同步更新此处，保证跨上下文类型安全。

export enum MessageType {
  AgentStatusUpdated = "AGENT_STATUS_UPDATED",
  TaskInfoUpdated = "TASK_INFO_UPDATED",
  ApprovalRequested = "APPROVAL_REQUESTED",
  ApprovalDecided = "APPROVAL_DECIDED",
  SettingsUpdated = "SETTINGS_UPDATED",
  ChatConversationsExtracted = "CHAT_CONVERSATIONS_EXTRACTED",
}

// Agent 状态机，对齐后端 TaskStatus
export type AgentState =
  | "idle"
  | "running"
  | "waiting_approval"
  | "waiting_hr"
  | "completed"
  | "failed"

export interface AgentStatusPayload {
  state: AgentState
  taskId?: string
  node?: string
  detail?: string
}

// Approval 敏感类型，对齐 spec Approval
export type ApprovalType =
  | "salary"
  | "location"
  | "start_date"
  | "overtime"
  | "outsourcing"
  | "probation_salary"

export interface ApprovalPayload {
  approvalId: string
  type: ApprovalType
  content: string
  expiresAt?: number
}

export interface ApprovalDecisionPayload {
  approvalId: string
  decision: "approved" | "rejected"
}

// 统一消息信封
export interface RuntimeMessage<T = unknown> {
  type: MessageType
  payload: T
}
