// 组件契约类型（设计权威：docs/前端页面布局/AI 求职 Agent UI 样式设计规范.md —— TS interface 统一在此定义）。
// 职责：Toast / 三态 StatusValue 等跨组件共享类型，
//       使 props 与 store 状态有单一事实来源，避免各组件重复声明字符串字面量。

/** Toast 种类：成功绿 / 错误红 / 信息主色（doc 12 §4.2 动作反馈） */
export type ToastKind = "success" | "error" | "info"

export interface Toast {
  id: string
  kind: ToastKind
  message: string
}

/**
 * 三态分离 + WS 连接态（状态色映射见 statusMeta.ts，遵循样式规范 §26/§34）。
 * agent_state / monitoring_state / task.status / ws_state 的值域，
 * UI 层状态权威；messages.ts 的 AgentState 为运行时线格式，保留但 UI 不再直接消费。
 */
export type AgentRunState = "idle" | "planning" | "executing" | "waiting_human" | "recovering" | "done"
export type MonitoringState = "idle" | "monitoring" | "paused" | "stopped"
export type TaskStatus = "pending" | "running" | "waiting_approval" | "recovering" | "succeeded" | "failed" | "canceled"
export type WsState = "connected" | "reconnecting" | "disconnected"

/** StatusBadge 可接收的任意状态值（并集，便于按 §4.3 映射） */
export type StatusValue = AgentRunState | MonitoringState | TaskStatus | WsState
