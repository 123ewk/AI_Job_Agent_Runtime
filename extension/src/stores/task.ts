// 任务 store（设计权威：前端布局 V1.0 §20，样式规范）。
// 职责：拉取任务列表、停止/重试任务。
// 后端契约（Phase 2 REST，schema/task.py + api/v1/tasks.py）：
//   - GET  /tasks?page=1&page_size=50  → PaginatedResponse<TaskResponse>（支持 status 筛选，本 V1 前端拉全量客户端筛选）
//   - POST /tasks/{id}/cancel          → StatusResponse（停止 pending/running）
//   - POST /tasks/{id}/retry           → TaskResponse（受 max_retries 约束）
// 设计取舍：一次拉全量（page_size=50）客户端按状态筛选 → 各 Tab 计数准确 + 切换即时；
//   任务量超过一页时后续会被截断（V1 单用户可接受，量大后改后端 status 筛选）。
// 操作采用本地乐观更新（停止→canceled、重试→pending），不回读，对齐 approval store 幂等风格。
import { defineStore } from "pinia"
import { ref } from "vue"
import type { TaskStatus } from "../types/components"
import { apiGet, apiPost } from "../lib/api"

/** 前端消费的任务（由 TaskResponse 映射） */
export interface TaskItem {
  id: number
  /** 任务类型（后端小写）：hr_reply / proactive_job / sync / ... */
  type: string
  status: TaskStatus
  /** 优先级（后端大写）：P0/P1/P2/P3 */
  priority: string
  retryCount: number
  maxRetries: number
  progress: number
  errorMessage: string | null
  conversationId: number | null
  jobId: number | null
  startedAt: string | null
  completedAt: string | null
  createdAt: string
}

/** 后端 TaskResponse（schema/task.py：id/type/status/priority/progress/error_message/...） */
interface TaskResponseDto {
  id: number
  user_id: number
  type: string
  status: string
  priority: string
  retry_count: number
  max_retries: number
  progress: number
  error_message: string | null
  result: Record<string, unknown> | null
  conversation_id: number | null
  job_id: number | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

interface StatusResponseDto {
  status: string
  message: string
}

/** 任务类型 → 中文标签（doc 03 八类） */
export const TASK_TYPE_LABELS: Record<string, string> = {
  hr_reply: "回复HR消息",
  proactive_chat: "主动沟通",
  proactive_job: "主动求职",
  sync: "数据同步",
  user_initiated: "用户触发",
  approval_resume: "确认后继续",
  recovery: "故障恢复",
  background_scan: "后台扫描",
}

/** 优先级 → 标签 + 色（P0 最高危，doc 04） */
export const TASK_PRIORITY_META: Record<string, { label: string; color: string }> = {
  P0: { label: "P0 紧急", color: "var(--color-danger)" },
  P1: { label: "P1 优先", color: "var(--color-warning)" },
  P2: { label: "P2 常规", color: "var(--color-info)" },
  P3: { label: "P3 后台", color: "var(--color-text-secondary)" },
}

function toTask(dto: TaskResponseDto): TaskItem {
  return {
    id: dto.id,
    type: dto.type,
    status: dto.status as TaskStatus,
    priority: dto.priority,
    retryCount: dto.retry_count,
    maxRetries: dto.max_retries,
    progress: dto.progress,
    errorMessage: dto.error_message,
    conversationId: dto.conversation_id,
    jobId: dto.job_id,
    startedAt: dto.started_at,
    completedAt: dto.completed_at,
    createdAt: dto.created_at,
  }
}

export const useTaskStore = defineStore("task", () => {
  const tasks = ref<TaskItem[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** 拉取任务列表（全量 + 客户端筛选，见文件头设计取舍） */
  async function fetchTasks(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await apiGet<{ items: TaskResponseDto[] }>("/tasks?page=1&page_size=50")
      tasks.value = res.items.map(toTask)
    } catch (e) {
      error.value = e instanceof Error ? e.message : "拉取任务列表失败"
    } finally {
      loading.value = false
    }
  }

  /** 停止任务（pending/running 可取消）；本地乐观置为 canceled */
  async function cancel(task: TaskItem): Promise<void> {
    await apiPost<StatusResponseDto>(`/tasks/${task.id}/cancel`, {})
    const t = tasks.value.find((x) => x.id === task.id)
    if (t) {
      t.status = "canceled"
      t.errorMessage = null
    }
  }

  /** 重试失败任务（受 max_retries 约束）；本地乐观置为 pending 并清零进度 */
  async function retry(task: TaskItem): Promise<void> {
    await apiPost<TaskResponseDto>(`/tasks/${task.id}/retry`, {})
    const t = tasks.value.find((x) => x.id === task.id)
    if (t) {
      t.status = "pending"
      t.progress = 0
      t.errorMessage = null
    }
  }

  return { tasks, loading, error, fetchTasks, cancel, retry }
})
