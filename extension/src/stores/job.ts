// 岗位 store（设计权威：前端布局 V1.0 §19，样式规范）。
// 职责：拉取最近岗位列表、删除岗位。
// 后端契约（Phase 2 REST，schema/job.py + api/v1/jobs.py）：
//   - GET    /jobs?page=1&page_size=10 → PaginatedResponse<JobResponse>（id 倒序 = 最近 10 条）
//   - DELETE /jobs/{id}                → StatusResponse（硬删除）
// 设计取舍：列表只取最近 10 条（用户确认，非全量）；状态筛选为客户端过滤（计数准确 + 切换即时）。
// 删除采用本地乐观移除（对齐 task/approval store 幂等风格），不回读后端。
import { defineStore } from "pinia"
import { ref } from "vue"
import { apiDelete, apiGet } from "../lib/api"

/** 评分明细（doc 09 schema：llm_score/llm_reason/keyword_hits/keyword_score/deductions） */
export interface ScoreDetail {
  llm_score: number
  llm_reason: string
  keyword_hits: string[]
  keyword_score: number
  deductions: string[]
}

/** 前端消费的岗位（由 JobResponse 映射） */
export interface JobItem {
  id: number
  platform: string
  externalId: string
  title: string | null
  company: string | null
  salary: string | null
  location: string | null
  description: string | null
  sourceUrl: string | null
  hrId: number | null
  status: string
  score: number | null
  scoreDetail: ScoreDetail | null
  createdAt: string
  updatedAt: string
}

/** 后端 JobResponse（schema/job.py：id/platform/external_id/.../status/score/score_detail/created_at/updated_at） */
interface JobResponseDto {
  id: number
  user_id: number
  platform: string
  external_id: string
  title: string | null
  company: string | null
  salary: string | null
  location: string | null
  description: string | null
  source_url: string | null
  hr_id: number | null
  status: string
  score: number | null
  score_detail: ScoreDetail | null
  created_at: string
  updated_at: string
}

interface StatusResponseDto {
  status: string
  message: string
}

/** 岗位状态 → 中文标签（doc 05 状态机；筛选 Tab 与空态共用） */
export const JOB_STATUS_LABELS: Record<string, string> = {
  discovered: "待处理",
  scored: "已匹配",
  chatting: "已进入聊天",
  applied: "已投递",
  rejected: "已拒绝",
  closed: "已关闭",
  skipped: "已跳过",
}

function toJob(dto: JobResponseDto): JobItem {
  return {
    id: dto.id,
    platform: dto.platform,
    externalId: dto.external_id,
    title: dto.title,
    company: dto.company,
    salary: dto.salary,
    location: dto.location,
    description: dto.description,
    sourceUrl: dto.source_url,
    hrId: dto.hr_id,
    status: dto.status,
    score: dto.score,
    scoreDetail: dto.score_detail ?? null,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  }
}

export const useJobStore = defineStore("job", () => {
  const jobs = ref<JobItem[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** 拉取最近岗位列表（page_size=10，后端 id 倒序 = 最近 10 条） */
  async function fetchJobs(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await apiGet<{ items: JobResponseDto[] }>("/jobs?page=1&page_size=10")
      jobs.value = res.items.map(toJob)
    } catch (e) {
      error.value = e instanceof Error ? e.message : "拉取岗位列表失败"
    } finally {
      loading.value = false
    }
  }

  /** 删除岗位（硬删除）；本地乐观移除，不回读 */
  async function remove(job: JobItem): Promise<void> {
    await apiDelete<StatusResponseDto>(`/jobs/${job.id}`)
    jobs.value = jobs.value.filter((x) => x.id !== job.id)
  }

  return { jobs, loading, error, fetchJobs, remove }
})
