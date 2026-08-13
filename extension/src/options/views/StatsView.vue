<script setup lang="ts">
// 统计页（设计权威：前端布局 V1.0 §48 高级统计；导航为第 8 项，用户已确认偏离 doc §6.1 七项）。
// 数据源组合（不新增后端聚合端点）：
//   - 顶部 3 卡：GET /users/me/stats（statsStore）—— 全量聚合，口径为准
//   - 岗位分布：jobStore.fetchJobs()（page_size=10，后端 id 倒序 = 最近 10 条）→ 客户端按 status 计数
//   - 任务分布：taskStore.fetchTasks()（page_size=50 全量）→ 客户端按 status 计数
// 口径差异如实标注：岗位分布仅覆盖最近 10 条，与顶部「岗位总数」卡数值不同。
import { computed, onMounted } from "vue"
import { BarChart3, Briefcase, Clock, MessageSquare, RefreshCw } from "lucide-vue-next"
import type { StatusValue } from "../../types/components"
import EmptyState from "../../components/common/EmptyState.vue"
import ErrorState from "../../components/common/ErrorState.vue"
import { jobStatusMeta } from "../../lib/statusMeta"
import { statusMeta } from "../../lib/statusMeta"
import { useJobStore } from "../../stores/job"
import { useStatsStore } from "../../stores/stats"
import { useTaskStore } from "../../stores/task"

const statsStore = useStatsStore()
const jobStore = useJobStore()
const taskStore = useTaskStore()

onMounted(() => {
  // 三路并行：统计聚合 + 最近岗位 + 任务列表（相互独立，无需串行）
  void Promise.all([statsStore.fetchStats(), jobStore.fetchJobs(), taskStore.fetchTasks()])
})

/** 岗位状态分布（最近 10 条）：status → count，降序 */
const jobDist = computed(() => {
  const counts = new Map<string, number>()
  for (const job of jobStore.jobs) {
    counts.set(job.status, (counts.get(job.status) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([status, count]) => ({ status, count, ...jobStatusMeta(status) }))
    .sort((a, b) => b.count - a.count)
})

/** 任务状态分布（全量 50 条）：status → count，降序 */
const taskDist = computed(() => {
  const counts = new Map<string, number>()
  for (const task of taskStore.tasks) {
    counts.set(task.status, (counts.get(task.status) ?? 0) + 1)
  }
  // 任务状态均在 StatusValue 值域内，Map 键为 string 需收窄（statusMeta 要求 StatusValue）
  return [...counts.entries()]
    .map(([status, count]) => ({ status, count, ...statusMeta(status as StatusValue) }))
    .sort((a, b) => b.count - a.count)
})

/** bar 宽度百分比：以最大 count 为 100%（至少 4% 保证可视） */
function barWidth(count: number, dist: { count: number }[]): string {
  const max = Math.max(1, ...dist.map((d) => d.count))
  return `${Math.max(4, (count / max) * 100)}%`
}

/** 重新拉取全部数据源（ErrorState 重试入口） */
function reload(): void {
  void Promise.all([statsStore.fetchStats(), jobStore.fetchJobs(), taskStore.fetchTasks()])
}
</script>

<template>
  <div class="stats-page">
    <header class="page-head">
      <h2 class="page-title">统计</h2>
      <button type="button" class="btn-refresh" aria-label="刷新统计" @click="reload">
        <RefreshCw :size="16" aria-hidden="true" />
      </button>
    </header>

    <ErrorState v-if="statsStore.error" :message="`统计加载失败：${statsStore.error}`" @retry="reload" />

    <div v-else-if="statsStore.loading" class="page-loading">加载统计中...</div>

    <template v-else>
      <!-- 顶部 3 张聚合卡（§48：全量口径为准） -->
      <section class="stat-cards" aria-label="统计概览">
        <div class="stat-card">
          <Clock :size="20" class="stat-icon" aria-hidden="true" />
          <div class="stat-body">
            <span class="stat-value">{{ statsStore.stats?.pendingTasks ?? 0 }}</span>
            <span class="stat-label">待处理任务</span>
          </div>
        </div>
        <div class="stat-card">
          <MessageSquare :size="20" class="stat-icon" aria-hidden="true" />
          <div class="stat-body">
            <span class="stat-value">{{ statsStore.stats?.activeConversations ?? 0 }}</span>
            <span class="stat-label">活跃会话</span>
          </div>
        </div>
        <div class="stat-card">
          <Briefcase :size="20" class="stat-icon" aria-hidden="true" />
          <div class="stat-body">
            <span class="stat-value">{{ statsStore.stats?.totalJobs ?? 0 }}</span>
            <span class="stat-label">岗位总数</span>
          </div>
        </div>
      </section>

      <!-- 岗位状态分布（口径：最近 10 条） -->
      <section class="dist-card">
        <header class="dist-head">
          <div class="dist-title">
            <BarChart3 :size="18" aria-hidden="true" />
            <h3 class="dist-name">岗位状态分布</h3>
          </div>
          <span class="dist-note">取最近 10 条岗位</span>
        </header>
        <EmptyState v-if="jobDist.length === 0" title="暂无岗位分布" hint="岗位列表为空，去岗位管理采集岗位" />
        <ul v-else class="dist-list">
          <li v-for="d in jobDist" :key="d.status" class="dist-item">
            <span class="dist-label">{{ d.label }}</span>
            <div class="dist-track">
              <div class="dist-bar" :style="{ width: barWidth(d.count, jobDist), background: d.color }" />
            </div>
            <span class="dist-count">{{ d.count }}</span>
          </li>
        </ul>
      </section>

      <!-- 任务状态分布（口径：最近 50 条全量） -->
      <section class="dist-card">
        <header class="dist-head">
          <div class="dist-title">
            <BarChart3 :size="18" aria-hidden="true" />
            <h3 class="dist-name">任务状态分布</h3>
          </div>
          <span class="dist-note">取最近 50 条任务</span>
        </header>
        <EmptyState v-if="taskDist.length === 0" title="暂无任务分布" hint="任务中心为空，Agent 开始工作后生成任务" />
        <ul v-else class="dist-list">
          <li v-for="d in taskDist" :key="d.status" class="dist-item">
            <span class="dist-label">{{ d.label }}</span>
            <div class="dist-track">
              <div class="dist-bar" :style="{ width: barWidth(d.count, taskDist), background: d.color }" />
            </div>
            <span class="dist-count">{{ d.count }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.stats-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.page-title {
  margin: 0;
  font-size: var(--fs-page-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.btn-refresh {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn-refresh:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.page-loading {
  padding: var(--space-8) 0;
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--fs-secondary);
}

/* 顶部 3 卡（§48 统计卡片：Grid 三等分） */
.stat-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
}

.stat-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.stat-icon {
  color: var(--color-primary);
}

.stat-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-value {
  font-size: 28px;
  font-weight: 600;
  line-height: 1.1;
  color: var(--color-text-primary);
}

.stat-label {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

/* 分布卡 */
.dist-card {
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.dist-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.dist-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-primary);
}

.dist-name {
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
}

.dist-note {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.dist-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.dist-item {
  display: grid;
  grid-template-columns: 88px 1fr 32px;
  align-items: center;
  gap: var(--space-3);
}

.dist-label {
  font-size: var(--fs-secondary);
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dist-track {
  height: 12px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-secondary);
  overflow: hidden;
}

.dist-bar {
  height: 100%;
  border-radius: var(--radius-pill);
  transition: width var(--transition-fast);
}

.dist-count {
  font-size: var(--fs-secondary);
  font-weight: 500;
  color: var(--color-text-primary);
  text-align: right;
}

@media (max-width: 640px) {
  .stat-cards {
    grid-template-columns: 1fr;
  }
}
</style>
