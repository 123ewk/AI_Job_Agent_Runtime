// 组件契约类型（设计权威：doc 12 §12.1 —— TS interface 统一在此定义）。
// 职责：TabId / Toast / 三态 StatusValue 等跨组件共享类型，
//       使 props 与 store 状态有单一事实来源，避免各组件重复声明字符串字面量。

/** SidePanel 6 个 Tab 标识（doc 12 §5.1：状态|Timeline|聊天|审批|日志|设置） */
export type TabId = "status" | "timeline" | "chat" | "approval" | "logs" | "settings"

/** Toast 种类：成功绿 / 错误红 / 信息主色（doc 12 §4.2 动作反馈） */
export type ToastKind = "success" | "error" | "info"

export interface Toast {
  id: string
  kind: ToastKind
  message: string
}

/**
 * 三态分离 + WS 连接态（doc 12 §4.3 状态色映射）。
 * agent_state / monitoring_state / task.status / ws_state 的值域，
 * 替代 Phase 1 单枚举混淆（Phase 1 旧 AgentState 见 types/messages.ts，待后续增量拆分）。
 */
export type AgentRunState = "idle" | "planning" | "executing" | "waiting_human" | "recovering" | "done"
export type MonitoringState = "idle" | "monitoring" | "paused" | "stopped"
export type TaskStatus = "running" | "waiting_approval" | "recovering" | "succeeded" | "failed" | "canceled"
export type WsState = "connected" | "reconnecting" | "disconnected"

/** StatusBadge 可接收的任意状态值（并集，便于按 §4.3 映射） */
export type StatusValue = AgentRunState | MonitoringState | TaskStatus | WsState
