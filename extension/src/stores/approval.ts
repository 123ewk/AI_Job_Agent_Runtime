// 人工确认 store（设计权威：前端布局 V1.0 §21/§21.1，样式规范 §27-§28）。
// 职责：发现并拉取待处理 Approval、通过/拒绝/停止任务决策。
// 后端契约（Phase 2 REST）：
//   - GET  /tasks?status=waiting_approval          → 发现当前待确认任务（单用户模式，取第一条）
//   - GET  /tasks/{id}/approvals/pending           → 该任务的 pending approval（最多一条）
//   - POST /tasks/{id}/approvals/approve           → 批准（body: approval_id/approved/user_note）
//   - POST /tasks/{id}/approvals/deny              → 拒绝
//   - POST /tasks/{id}/cancel                      → 「我知道了」停止当前任务（§21.1）
// 已知缺口：后端无历史审批列表接口 → 筛选 Tab 仅「待处理/全部」有数据，其余渲染空态并标注（Phase 2 补齐）。
// 前端幂等：decide 成功后本地移除该条，不依赖后端回读（后端 approve/deny 对已决策项为 no-op，GC-safe）。
import { defineStore } from "pinia"
import { ref } from "vue"
import { apiGet, apiPost } from "../lib/api"

/** 前端消费的待确认项（由后端 ApprovalResponse 映射而来） */
export interface PendingApproval {
  approvalId: number
  taskId: number
  /** 确认类型（backend ApprovalType 小写：salary/location/...） */
  type: string
  /** 展示内容（优先 payload.question，回退 payload 摘要） */
  content: string
  /** ISO 时间串；null 表示无超时 */
  expiresAt: string | null
  createdAt: string
}

/** 后端 ApprovalResponse（schema/task.py：id/task_id/type/payload/status/expires_at...） */
interface ApprovalResponseDto {
  id: number
  task_id: number
  user_id: number
  type: string
  payload: Record<string, unknown>
  status: string
  expires_at: string | null
  decided_at: string | null
  created_at: string
}

/** 后端任务列表项（仅取 status 判定待确认任务） */
interface TaskListItemDto {
  id: number
  status: string
}

/** 后端 StatusResponse（approve/deny/cancel 统一返回 {status, message}） */
interface StatusResponseDto {
  status: string
  message: string
}

/** 确认类型 → 中文标签（doc 14 敏感字段：薪资/地点/入职时间/加班/外包/远程/试用期薪资） */
export const APPROVAL_TYPE_LABELS: Record<string, string> = {
  salary: "薪资",
  location: "地点",
  start_date: "入职时间",
  overtime: "加班",
  outsourcing: "外包",
  offsite: "远程",
  probation_salary: "试用期薪资",
}

/** payload 是 JSONB（结构由 Agent 侧决定），尽力提取可读文案，兜底序列化 */
function extractContent(payload: Record<string, unknown>): string {
  if (typeof payload.question === "string" && payload.question) return payload.question
  if (typeof payload.hr_quote === "string" && payload.hr_quote) return payload.hr_quote
  if (typeof payload.suggestion === "string" && payload.suggestion) return payload.suggestion
  return JSON.stringify(payload)
}

function toPending(dto: ApprovalResponseDto): PendingApproval {
  return {
    approvalId: dto.id,
    taskId: dto.task_id,
    type: dto.type,
    content: extractContent(dto.payload),
    expiresAt: dto.expires_at,
    createdAt: dto.created_at,
  }
}

export const useApprovalStore = defineStore("approval", () => {
  const pending = ref<PendingApproval[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /**
   * 刷新待确认列表：先发现 waiting_approval 任务，再拉取其 pending approval。
   * 单用户模式（user_id=1）无「当前任务」端点，故用状态筛选兜底（V1 阶段可接受）。
   */
  async function refresh(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const tasks = await apiGet<{ items: TaskListItemDto[] }>("/tasks?status=waiting_approval&page_size=10")
      const target = tasks.items[0]
      if (!target) {
        pending.value = []
        return
      }
      const res = await apiGet<ApprovalResponseDto | null>(`/tasks/${target.id}/approvals/pending`)
      pending.value = res ? [toPending(res)] : []
    } catch (e) {
      // 拉取失败不抛出：页面显示错误态并给「重试」入口（文档 §51：UI 不猜测后端状态）
      error.value = e instanceof Error ? e.message : "拉取待确认失败"
    } finally {
      loading.value = false
    }
  }

  /** 批准：POST approve（body 需 approval_id/approved）；成功后本地移除，保持幂等 */
  async function approve(approval: PendingApproval): Promise<void> {
    await apiPost<StatusResponseDto>(`/tasks/${approval.taskId}/approvals/approve`, {
      approval_id: approval.approvalId,
      approved: true,
    })
    pending.value = pending.value.filter((a) => a.approvalId !== approval.approvalId)
  }

  /** 拒绝：POST deny；任务进入 canceled 终态 */
  async function deny(approval: PendingApproval): Promise<void> {
    await apiPost<StatusResponseDto>(`/tasks/${approval.taskId}/approvals/deny`, {})
    pending.value = pending.value.filter((a) => a.approvalId !== approval.approvalId)
  }

  /** 「我知道了」（§21.1）：停止当前任务（POST cancel），并移除该待确认项 */
  async function stopTask(approval: PendingApproval): Promise<void> {
    await apiPost<StatusResponseDto>(`/tasks/${approval.taskId}/cancel`, {})
    pending.value = pending.value.filter((a) => a.approvalId !== approval.approvalId)
  }

  return { pending, loading, error, refresh, approve, deny, stopTask }
})
