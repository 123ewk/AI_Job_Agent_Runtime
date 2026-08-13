// 时间格式化工具（聊天/任务/日志通用）。
// 职责：ISO 时间串 → 相对时间（刚刚/N 分钟前/N 小时前/昨天/N 天前/日期）与时钟（HH:mm）。
// 原理：后端存 UTC ISO 串，前端仅做本地展示；相对时间用本地时钟差值计算，避免手写时区换算。
export function formatRelativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—"
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return "—"
  const diffMin = Math.floor((now - t) / 60000)
  if (diffMin < 1) return "刚刚"
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 2) return "昨天"
  if (diffDay < 7) return `${diffDay} 天前`
  return formatDate(iso)
}

/** 完整日期（yyyy-MM-dd）；解析失败回退原串 */
export function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

/** 时钟（HH:mm）；空串/非法输入回退空串 */
export function formatClock(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
}
