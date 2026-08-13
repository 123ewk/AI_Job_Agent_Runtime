// 三态状态 → label/color 映射（设计权威：docs/前端页面布局/AI 求职 Agent UI 样式设计规范.md §26/§34 状态色映射）。
// 职责：集中维护 agent_state / monitoring_state / task.status / ws_state 的展示元数据，
//       StatusBadge、ConnectIndicator 及 Timeline/EventLog 等组件统一消费，避免散落硬编码。
// 原理：色值引用 CSS 变量而非十六进制，主题切换（data-theme）时无需改动映射。

import type { StatusValue } from "../types/components"

export interface StatusMeta {
  label: string
  /** CSS 变量引用（如 var(--color-success)），由 tokens.css 解析 */
  color: string
  /** 脉冲动效：recovering / reconnecting（doc 12 §4.3 标注） */
  pulse?: boolean
}

// 注：不同状态字段可能共享同一字符串值（如 agent_state.idle 与 monitoring_state.idle），
// 按字符串唯一键归并，符合 §4.3 同一值同一色的语义。
const META: Record<StatusValue, StatusMeta> = {
  // agent_state
  idle: { label: "空闲", color: "var(--color-text-secondary)" },
  planning: { label: "规划中", color: "var(--color-info)" },
  executing: { label: "执行中", color: "var(--color-info)" },
  waiting_human: { label: "等待人工", color: "var(--color-warning)" },
  recovering: { label: "恢复中", color: "var(--color-warning)", pulse: true },
  done: { label: "已完成", color: "var(--color-success)" },
  // monitoring_state
  monitoring: { label: "监听中", color: "var(--color-success)" },
  paused: { label: "已暂停", color: "var(--color-warning)" },
  stopped: { label: "已停止", color: "var(--color-danger)" },
  // task.status
  pending: { label: "等待中", color: "var(--color-info)" },
  running: { label: "运行中", color: "var(--color-info)" },
  waiting_approval: { label: "待确认", color: "var(--color-warning)" },
  succeeded: { label: "成功", color: "var(--color-success)" },
  failed: { label: "失败", color: "var(--color-danger)" },
  canceled: { label: "已取消", color: "var(--color-text-secondary)" },
  // ws_state
  connected: { label: "已连接", color: "var(--color-success)" },
  reconnecting: { label: "重连中", color: "var(--color-warning)", pulse: true },
  disconnected: { label: "未连接", color: "var(--color-danger)" },
}

/** 零信任兜底：未知状态值不抛错，回退为文本色 + 原值。 */
export function statusMeta(status: StatusValue): StatusMeta {
  return META[status] ?? { label: status, color: "var(--color-text-secondary)" }
}

// 会话状态（conversation.status：active / waiting_hr / closed）→ 展示元数据。
// 与三态映射分开：会话状态值域不同，复用 StatusValue 会引入无关状态，故独立函数 + 零信任兜底。
const CONV_STATUS_META: Record<string, { label: string; color: string }> = {
  active: { label: "进行中", color: "var(--color-success)" },
  waiting_hr: { label: "等待HR", color: "var(--color-warning)" },
  closed: { label: "已关闭", color: "var(--color-text-secondary)" },
}

export function conversationStatusMeta(status: string): { label: string; color: string } {
  return CONV_STATUS_META[status] ?? { label: status, color: "var(--color-text-secondary)" }
}

// 岗位状态（job.status：discovered/scored/chatting/applied/rejected/closed/skipped，小写）→ 展示元数据。
// 与三态/会话映射分开：岗位状态值域独立，仿 conversationStatusMeta 独立函数 + 零信任兜底。
const JOB_STATUS_META: Record<string, { label: string; color: string }> = {
  discovered: { label: "待处理", color: "var(--color-text-secondary)" },
  scored: { label: "已匹配", color: "var(--color-success)" },
  chatting: { label: "已进入聊天", color: "var(--color-info)" },
  applied: { label: "已投递", color: "var(--color-primary)" },
  rejected: { label: "已拒绝", color: "var(--color-danger)" },
  closed: { label: "已关闭", color: "var(--color-text-secondary)" },
  skipped: { label: "已跳过", color: "var(--color-text-secondary)" },
}

export function jobStatusMeta(status: string): { label: string; color: string } {
  return JOB_STATUS_META[status] ?? { label: status, color: "var(--color-text-secondary)" }
}
