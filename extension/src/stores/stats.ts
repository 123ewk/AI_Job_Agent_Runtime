// 统计 store（设计权威：[[stats-page-design-feedback]]——V2 重构为「AI Agent 数据控制台」）。
// 职责：统一提供统计页 4 类数据，数据结构对齐「最终 API 形态」，页面组件不硬编码数据：
//   statistics      {pendingTasks, activeConversations, totalJobs, todayProcessed}  ← GET /users/me/stats + 推导
//   jobStatistics   {applied, chatting, matched, pending}   ← 复用 jobStore 客户端计数（最近 10 条岗位）
//   taskStatistics  {pending, running, waitingApproval, completed, failed} ← 复用 taskStore 客户端计数（全量 50）
//   recentJobs      [{id, company_name, position_name, match_score, status, updated_at}] ← jobStore 映射
// 口径差异如实标注：jobStatistics/recentJobs 覆盖 jobStore 最近 10 条，statistics.totalJobs 为全量 →
//   岗位环形图中心=全量总数，分段=最近 10 条分布（与 KPI「岗位总数」数值口径不同，页面图例区标注）。
// todayProcessed：后端 statistics 接口暂缺该字段，V1 由任务 store 推导（终态且完成于今日）；
//   后端补字段后改为直接从 statistics 读，推导逻辑可整体删除。
import { computed, ref } from "vue"
import { defineStore } from "pinia"
import { apiGet } from "../lib/api"
import { useJobStore } from "./job"
import { useTaskStore } from "./task"

/** 后端 /users/me/stats 原始响应（snake_case；today_processed 为预留字段，后端暂未返回） */
interface UserStatsDto {
  pending_tasks: number
  active_conversations: number
  total_jobs: number
}

/** 顶部 KPI 聚合（statistics 最终 API 形态，camelCase） */
export interface Statistics {
  pendingTasks: number
  activeConversations: number
  totalJobs: number
  todayProcessed: number
}

/** 岗位状态分布（job_statistics 最终 API 形态；semantic 键 ← 原始 job.status） */
export interface JobStatistics {
  applied: number // ← "applied"
  chatting: number // ← "chatting"
  matched: number // ← "scored"（评分达标即「已匹配」）
  pending: number // ← "discovered"
}

/** 任务状态分布（task_statistics 最终 API 形态） */
export interface TaskStatistics {
  pending: number // ← "pending"
  running: number // ← "running"
  waitingApproval: number // ← "waiting_approval"
  completed: number // ← "succeeded"
  failed: number // ← "failed"
}

/** 最近岗位（recent_jobs 最终 API 形态） */
export interface RecentJob {
  id: number
  company_name: string | null
  position_name: string | null
  match_score: number | null
  status: string
  updated_at: string
}

export const useStatsStore = defineStore("stats", () => {
  const statistics = ref<Statistics | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const jobStore = useJobStore()
  const taskStore = useTaskStore()

  /** 今日处理：V1 由任务 store 推导（终态且完成于今日）；后端补 today_processed 后改读字段 */
  function computeTodayProcessed(): number {
    const today = new Date().toDateString()
    return taskStore.tasks.filter((t) => t.completedAt && new Date(t.completedAt).toDateString() === today).length
  }

  async function fetchStatistics(): Promise<void> {
    const dto = await apiGet<UserStatsDto>("/users/me/stats")
    statistics.value = {
      pendingTasks: dto.pending_tasks,
      activeConversations: dto.active_conversations,
      totalJobs: dto.total_jobs,
      todayProcessed: computeTodayProcessed(),
    }
  }

  /** 三路并行拉取（KPI + 最近岗位 + 任务列表）；任一失败置页面级 error，便于统一 Error 态 */
  async function fetchAll(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const results = await Promise.allSettled([fetchStatistics(), jobStore.fetchJobs(), taskStore.fetchTasks()])
      if (results[0].status === "rejected") {
        error.value = results[0].reason instanceof Error ? results[0].reason.message : "拉取统计失败"
      } else if (jobStore.error) {
        error.value = jobStore.error
      } else if (taskStore.error) {
        error.value = taskStore.error
      }
    } finally {
      loading.value = false
    }
  }

  /** 岗位状态分布（最近 10 条岗位）；rejected/closed/skipped 为终态/忽略状态，不计入活动管线 */
  const jobStatistics = computed<JobStatistics>(() => {
    const jobs = jobStore.jobs
    return {
      applied: jobs.filter((j) => j.status === "applied").length,
      chatting: jobs.filter((j) => j.status === "chatting").length,
      matched: jobs.filter((j) => j.status === "scored").length,
      pending: jobs.filter((j) => j.status === "discovered").length,
    }
  })

  /** 任务状态分布（最近 50 条全量） */
  const taskStatistics = computed<TaskStatistics>(() => {
    const tasks = taskStore.tasks
    return {
      pending: tasks.filter((t) => t.status === "pending").length,
      running: tasks.filter((t) => t.status === "running").length,
      waitingApproval: tasks.filter((t) => t.status === "waiting_approval").length,
      completed: tasks.filter((t) => t.status === "succeeded").length,
      failed: tasks.filter((t) => t.status === "failed").length,
    }
  })

  /** 最近岗位（透传 jobStore 列表映射；后端聚合端点出现后替换数据源即可） */
  const recentJobs = computed<RecentJob[]>(() =>
    jobStore.jobs.map((j) => ({
      id: j.id,
      company_name: j.company,
      position_name: j.title,
      match_score: j.score,
      status: j.status,
      updated_at: j.updatedAt,
    }))
  )

  return { statistics, loading, error, fetchAll, jobStatistics, taskStatistics, recentJobs }
})
