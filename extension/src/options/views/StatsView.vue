<script setup lang="ts">
// 统计页（设计权威：[[stats-page-design-feedback]]——V2 重构为「简洁、现代、专业的 AI Agent 数据控制台」；
// 导航为侧栏第 8 项「统计」，用户已确认偏离 doc §6.1 七项）。
// 布局：4 KPI → 岗位状态(环形+列表) | 任务状态(受限宽列表) → 最近岗位表。
// 数据源：statsStore.fetchAll() 三路并行（/users/me/stats + jobStore + taskStore），组件不硬编码数据。
// 五态：Offline（后端未连接）> Loading(Skeleton) > Error > Empty(分区) > 内容。
// 口径标注：岗位环形图中心=全量岗位总数（KPI 口径），分段=最近 10 条岗位分布（jobStore page_size=10）。
import { computed, onMounted } from "vue"
import { useRouter } from "vue-router"
import { Briefcase, CheckCircle2, Clock, MessageSquare, RefreshCw, WifiOff } from "lucide-vue-next"
import EmptyState from "../../components/common/EmptyState.vue"
import ErrorState from "../../components/common/ErrorState.vue"
import Skeleton from "../../components/common/Skeleton.vue"
import StatusRing, { type RingSegment } from "../../components/stats/StatusRing.vue"
import { jobStatusMeta } from "../../lib/statusMeta"
import { formatRelativeTime } from "../../lib/time"
import { useConnectionStore } from "../../stores/connection"
import { useStatsStore } from "../../stores/stats"

const statsStore = useStatsStore()
const connection = useConnectionStore()
const router = useRouter()

onMounted(() => {
  void connection.checkHealth()
  void statsStore.fetchAll()
})

/** 后端未连接（健康检查失败）：优先于 Error/Loading 展示，避免「数据失败」误导 */
const offline = computed(() => !statsStore.loading && connection.state === "disconnected")

/** 重新拉取全部数据（Offline/Error/刷新按钮共用入口） */
function reload(): void {
  void connection.checkHealth()
  void statsStore.fetchAll()
}

/** 岗位详情在 /jobs（主从布局）承载；统计页仅保留跳转入口，不新建详情页 */
function goToJobs(): void {
  void router.push("/jobs")
}

/* ===== 顶部 KPI 配置（图标语义色：待处理橙 / 会话蓝 / 岗位灰 / 今日绿，避免蓝色泛滥） ===== */
const kpiCards = computed(() => {
  const s = statsStore.statistics
  return [
    { label: "待处理任务", note: "需要关注", value: s?.pendingTasks ?? 0, icon: Clock, color: "var(--color-warning)" },
    { label: "活跃会话", note: "正在推进", value: s?.activeConversations ?? 0, icon: MessageSquare, color: "var(--color-info)" },
    { label: "岗位总数", note: "已入库岗位", value: s?.totalJobs ?? 0, icon: Briefcase, color: "var(--color-text-secondary)" },
    { label: "今日处理", note: "Agent 今日完成", value: s?.todayProcessed ?? 0, icon: CheckCircle2, color: "var(--color-success)" },
  ]
})

/* ===== 岗位环形图分段（已投递蓝 / 已进入聊天蓝 / 已匹配绿 / 待处理灰） ===== */
const jobSegments = computed<RingSegment[]>(() => {
  const j = statsStore.jobStatistics
  return [
    { label: "已投递", count: j.applied, color: "var(--color-primary)" },
    { label: "已进入聊天", count: j.chatting, color: "var(--color-info)" },
    { label: "已匹配", count: j.matched, color: "var(--color-success)" },
    { label: "待处理", count: j.pending, color: "var(--color-text-secondary)" },
  ]
})

/* ===== 任务状态列表（固定顺序；执行中蓝 / 等待确认橙 / 已完成绿 / 失败红 / 其它灰） ===== */
const taskRows = computed(() => {
  const t = statsStore.taskStatistics
  return [
    { label: "待处理", count: t.pending, color: "var(--color-text-secondary)" },
    { label: "执行中", count: t.running, color: "var(--color-primary)" },
    { label: "等待确认", count: t.waitingApproval, color: "var(--color-warning)" },
    { label: "已完成", count: t.completed, color: "var(--color-success)" },
    { label: "失败", count: t.failed, color: "var(--color-danger)" },
  ]
})

/** bar 填充宽度：以最大 count 为 100%（track 本身 ≤220px，不再铺满页面） */
function taskBarWidth(count: number): string {
  const max = Math.max(1, ...taskRows.value.map((r) => r.count))
  return `${(count / max) * 100}%`
}

/** 匹配度 Badge 元数据：≥80 绿色积极，<80 中性，无分灰「待评分」 */
function matchMeta(score: number | null): { label: string; cls: string } {
  if (score == null) return { label: "待评分", cls: "match-none" }
  const s = Math.round(score)
  return { label: `${s}%`, cls: s >= 80 ? "match-high" : "match-mid" }
}
</script>

<template>
  <div class="stats-page">
    <header class="page-head">
      <h2 class="page-title">统计</h2>
      <button
        type="button"
        class="btn-refresh"
        aria-label="刷新统计"
        :disabled="statsStore.loading"
        @click="reload"
      >
        <RefreshCw :size="16" aria-hidden="true" :class="{ spinning: statsStore.loading }" />
      </button>
    </header>

    <!-- 1. Offline：后端未连接 -->
    <div v-if="offline" class="offline-box">
      <WifiOff :size="28" class="offline-icon" aria-hidden="true" />
      <p class="offline-title">当前无法连接 Agent Runtime</p>
      <p class="offline-hint">请确认后端服务已启动后重试</p>
      <button type="button" class="offline-btn" @click="reload">重新加载</button>
    </div>

    <!-- 2. Loading：Skeleton（禁转圈文案） -->
    <div v-else-if="statsStore.loading" class="skeleton-page" aria-label="加载统计中">
      <div class="skeleton-kpis">
        <Skeleton v-for="i in 4" :key="i" type="card" />
      </div>
      <div class="skeleton-cards">
        <Skeleton type="card" />
        <Skeleton type="card" />
      </div>
      <Skeleton type="card" />
    </div>

    <!-- 3. Error -->
    <ErrorState
      v-else-if="statsStore.error"
      :message="`无法获取统计数据：${statsStore.error}`"
      @retry="reload"
    />

    <!-- 4. 内容 -->
    <template v-else>
      <!-- 顶部 4 KPI -->
      <section class="kpi-grid" aria-label="统计概览">
        <div v-for="card in kpiCards" :key="card.label" class="kpi-card">
          <div class="kpi-head">
            <span class="kpi-label">{{ card.label }}</span>
            <component :is="card.icon" :size="18" class="kpi-icon" :style="{ color: card.color }" aria-hidden="true" />
          </div>
          <span class="kpi-value">{{ card.value }}</span>
          <span class="kpi-note">{{ card.note }}</span>
        </div>
      </section>

      <!-- 岗位状态（环形 + 图例） | 任务状态（受限宽列表） -->
      <section class="middle-grid">
        <div class="panel">
          <header class="panel-head">
            <h3 class="panel-title">岗位状态</h3>
            <span class="panel-note">最近 10 条</span>
          </header>
          <EmptyState
            v-if="(statsStore.statistics?.totalJobs ?? 0) === 0"
            title="暂无岗位数据"
            hint="开始寻找适合你的岗位"
          >
            <button type="button" class="link-btn" @click="goToJobs">开始寻找适合你的岗位 →</button>
          </EmptyState>
          <StatusRing
            v-else
            :segments="jobSegments"
            :total="statsStore.statistics?.totalJobs ?? 0"
            caption="岗位"
          />
        </div>

        <div class="panel">
          <header class="panel-head">
            <h3 class="panel-title">任务状态</h3>
            <span class="panel-note">最近 50 条</span>
          </header>
          <EmptyState
            v-if="taskRows.every((r) => r.count === 0)"
            title="暂无任务"
            hint="Agent 开始工作后生成任务"
          />
          <ul v-else class="task-list">
            <li v-for="row in taskRows" :key="row.label" class="task-item">
              <div class="task-meta">
                <span class="task-label">{{ row.label }}</span>
                <span class="task-count">{{ row.count }}</span>
              </div>
              <div class="task-track">
                <div class="task-bar" :style="{ width: taskBarWidth(row.count), background: row.color }" />
              </div>
            </li>
          </ul>
        </div>
      </section>

      <!-- 最近岗位 -->
      <section class="panel recent-panel">
        <header class="panel-head">
          <h3 class="panel-title">最近岗位</h3>
          <button type="button" class="link-btn" @click="goToJobs">查看全部 →</button>
        </header>
        <EmptyState
          v-if="statsStore.recentJobs.length === 0"
          title="暂无岗位数据"
          hint="开始寻找适合你的岗位"
        >
          <button type="button" class="link-btn" @click="goToJobs">开始寻找适合你的岗位 →</button>
        </EmptyState>
        <div v-else class="table-scroll">
          <div class="jobs-table">
            <div class="table-head">
              <span>公司</span>
              <span>职位</span>
              <span>匹配度</span>
              <span>状态</span>
              <span>时间</span>
            </div>
            <button
              v-for="job in statsStore.recentJobs"
              :key="job.id"
              type="button"
              class="table-row"
              @click="goToJobs"
            >
              <span class="cell-company">{{ job.company_name || "—" }}</span>
              <span class="cell-position">{{ job.position_name || "—" }}</span>
              <span class="cell-match">
                <span
                  class="match-badge"
                  :class="matchMeta(job.match_score).cls"
                >{{ matchMeta(job.match_score).label }}</span>
              </span>
              <span class="cell-status">
                <span
                  class="table-badge"
                  :style="{
                    color: jobStatusMeta(job.status).color,
                    background: `color-mix(in srgb, ${jobStatusMeta(job.status).color} 12%, transparent)`,
                  }"
                >{{ jobStatusMeta(job.status).label }}</span>
              </span>
              <span class="cell-time">{{ formatRelativeTime(job.updated_at) }}</span>
            </button>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
/* 页面容器：max-width 1400，左右留白（依赖 DashboardLayout main-content 的 18px padding + 自身居中） */
.stats-page {
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
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

.btn-refresh:hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.btn-refresh:disabled {
  cursor: default;
  opacity: 0.7;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ===== Offline ===== */
.offline-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-10) var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  text-align: center;
}

.offline-icon {
  color: var(--color-text-tertiary);
}

.offline-title {
  margin: 0;
  font-size: var(--fs-body);
  font-weight: 500;
  color: var(--color-text-primary);
}

.offline-hint {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.offline-btn {
  margin-top: var(--space-2);
  padding: var(--space-1) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  font-size: var(--fs-aux);
  cursor: pointer;
  transition: border-color var(--transition-fast);
}

.offline-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* ===== Skeleton ===== */
.skeleton-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.skeleton-kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-4);
}

.skeleton-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-4);
}

/* ===== 顶部 KPI ===== */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-4);
}

.kpi-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: var(--space-2);
  height: 100px;
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.kpi-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.kpi-label {
  font-size: var(--fs-secondary);
  color: var(--color-text-secondary);
}

.kpi-icon {
  flex-shrink: 0;
}

.kpi-value {
  font-size: var(--fs-number);
  font-weight: 600;
  line-height: 1;
  color: var(--color-text-primary);
}

.kpi-note {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

/* ===== 第二行：岗位/任务面板 ===== */
.middle-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-4);
  align-items: stretch;
}

.panel {
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.panel-title {
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.panel-note {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.link-btn {
  border: none;
  background: transparent;
  color: var(--color-primary);
  font-size: var(--fs-secondary);
  cursor: pointer;
  padding: 0;
  transition: color var(--transition-fast);
}

.link-btn:hover {
  color: var(--color-primary-hover);
}

/* ===== 任务状态列表（track ≤220px，不铺满） ===== */
.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.task-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.task-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.task-label {
  font-size: var(--fs-secondary);
  color: var(--color-text-secondary);
}

.task-count {
  font-size: var(--fs-secondary);
  font-weight: 600;
  color: var(--color-text-primary);
}

.task-track {
  width: 220px;
  max-width: 100%;
  height: 8px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-secondary);
  overflow: hidden;
}

.task-bar {
  height: 100%;
  border-radius: var(--radius-pill);
  transition: width var(--transition-fast);
}

/* ===== 最近岗位表 ===== */
.table-scroll {
  overflow-x: auto;
}

.jobs-table {
  min-width: 560px;
}

.table-head,
.table-row {
  display: grid;
  grid-template-columns: 1.2fr 1.6fr 88px 116px 92px;
  align-items: center;
  column-gap: var(--space-3);
}

.table-head {
  padding: 0 var(--space-2) var(--space-2);
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
  border-bottom: 1px solid var(--color-border);
}

.table-row {
  width: 100%;
  padding: 0 var(--space-2);
  height: 52px;
  border: none;
  background: transparent;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.table-row:hover {
  background: var(--color-bg-secondary);
}

.table-row:last-child {
  border-bottom: none;
}

.cell-company {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-position {
  font-size: var(--fs-body);
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.match-badge,
.table-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  font-size: var(--fs-badge);
  font-weight: 500;
}

.match-high {
  background: rgba(34, 197, 94, 0.12);
  color: var(--color-success);
}

.match-mid {
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
}

.match-none {
  background: var(--color-bg-secondary);
  color: var(--color-text-tertiary);
}

.cell-time {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

/* ===== 响应式 ===== */
@media (max-width: 1199px) {
  .kpi-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 900px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .middle-grid {
    grid-template-columns: 1fr;
  }

  .skeleton-kpis {
    grid-template-columns: repeat(2, 1fr);
  }

  .skeleton-cards {
    grid-template-columns: 1fr;
  }
}
</style>
