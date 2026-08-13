// 统计 store（设计权威：前端布局 V1.0 §48 高级统计 + 第三阶段 §48）。
// 职责：拉取用户统计聚合（GET /users/me/stats），供统计页头部 3 张卡片消费。
// 后端契约（Phase 2 REST，api/v1/users.py）：返回 { pending_tasks, active_conversations, total_jobs }。
// 设计取舍：仅三项聚合数值（后端一次 count 查询）；分布类数据由统计页复用
//   jobStore.fetchJobs / taskStore.fetchTasks 现成列表做客户端计数，不新增后端聚合端点。
import { defineStore } from "pinia"
import { ref } from "vue"
import { apiGet } from "../lib/api"

/** 后端 /users/me/stats 原始响应（snake_case） */
export interface UserStatsDto {
  pending_tasks: number
  active_conversations: number
  total_jobs: number
}

/** 前端消费的统计聚合（映射为 camelCase） */
export interface UserStats {
  pendingTasks: number
  activeConversations: number
  totalJobs: number
}

export const useStatsStore = defineStore("stats", () => {
  const stats = ref<UserStats | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** 拉取统计聚合（每次进入统计页调用，数据量小无需缓存） */
  async function fetchStats(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const dto = await apiGet<UserStatsDto>("/users/me/stats")
      stats.value = {
        pendingTasks: dto.pending_tasks,
        activeConversations: dto.active_conversations,
        totalJobs: dto.total_jobs,
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : "拉取统计失败"
    } finally {
      loading.value = false
    }
  }

  return { stats, loading, error, fetchStats }
})
