// 简历 store（设计权威：前端布局 V1.0 §30 简历管理）。
// 职责：拉取简历列表、查看详情、导入（新建）、设为默认、删除。
// 后端契约（I12 新增，schema/resume.py + api/v1/resume.py）：
//   - GET    /resumes?page=1&page_size=20 → PaginatedResponse<ResumeResponse>（更新时间倒序）
//   - GET    /resumes/{id}                → ResumeDetailResponse（含 content 原文）
//   - POST   /resumes                     → ResumeResponse（JSON {name, content}，非 multipart）
//   - POST   /resumes/{id}/activate       → ResumeResponse（设默认）
//   - DELETE /resumes/{id}                → StatusResponse
// 设计取舍：
//   - 列表只取最近 20 条（V1 简历数量少，足够）；导入/删除本地更新列表，不回读。
//   - summary_preview 后端 V1 恒为 None（Agent 摘要管线未接线），UI 显示 gap-note。
import { defineStore } from "pinia"
import { ref } from "vue"
import { apiDelete, apiGet, apiPost } from "../lib/api"

/** 前端消费的简历（由 ResumeResponse 映射） */
export interface ResumeItem {
  id: number
  name: string
  version: number
  status: string
  isDefault: boolean
  summaryPreview: string | null
  createdAt: string
  updatedAt: string
  /** 仅详情接口返回（查看原文用） */
  content?: string | null
}

/** 后端 ResumeResponse（schema/resume.py：id/user_id/name/version/status/is_default/summary_preview/created_at/updated_at） */
interface ResumeResponseDto {
  id: number
  user_id: number
  name: string
  version: number
  status: string
  is_default: boolean
  summary_preview: string | null
  created_at: string
  updated_at: string
}

interface ResumeDetailDto extends ResumeResponseDto {
  content: string | null
}

interface StatusResponseDto {
  status: string
  message: string
}

function toResume(dto: ResumeResponseDto): ResumeItem {
  return {
    id: dto.id,
    name: dto.name,
    version: dto.version,
    status: dto.status,
    isDefault: dto.is_default,
    summaryPreview: dto.summary_preview,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  }
}

export const useResumeStore = defineStore("resume", () => {
  const resumes = ref<ResumeItem[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** 拉取简历列表（page_size=20） */
  async function fetchList(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await apiGet<{ items: ResumeResponseDto[] }>("/resumes?page=1&page_size=20")
      resumes.value = res.items.map(toResume)
    } catch (e) {
      error.value = e instanceof Error ? e.message : "拉取简历列表失败"
    } finally {
      loading.value = false
    }
  }

  /** 拉取简历详情（含原文 content） */
  async function fetchDetail(id: number): Promise<ResumeItem> {
    const dto = await apiGet<ResumeDetailDto>(`/resumes/${id}`)
    return { ...toResume(dto), content: dto.content }
  }

  /** 导入简历（V1 JSON 文本：name + content）；列表本地前插 */
  async function create(name: string, content: string): Promise<ResumeItem> {
    const dto = await apiPost<ResumeResponseDto>("/resumes", { name, content })
    const item = toResume(dto)
    resumes.value = [item, ...resumes.value]
    return item
  }

  /** 设为默认；本地先清后置（对齐后端 clear_default + set 语义） */
  async function activate(id: number): Promise<void> {
    const dto = await apiPost<ResumeResponseDto>(`/resumes/${id}/activate`, {})
    resumes.value = resumes.value.map((r) => ({ ...r, isDefault: r.id === dto.id }))
  }

  /** 删除简历；本地乐观移除，不回读 */
  async function remove(id: number): Promise<void> {
    await apiDelete<StatusResponseDto>(`/resumes/${id}`)
    resumes.value = resumes.value.filter((r) => r.id !== id)
  }

  return { resumes, loading, error, fetchList, fetchDetail, create, activate, remove }
})
