<script setup lang="ts">
// 岗位管理页（设计权威：前端布局 V1.0 §19，样式规范）。
// 结构：状态筛选 Tab + 主从布局（左侧岗位列表 + 右侧详情面板，§19「筛选栏→岗位列表→岗位详情」）。
// 数据：job store 拉最近 10 条后客户端筛选（各 Tab 计数准确 + 切换即时）。
// 选中态：fetch/刷新/删除后经 watch 自动回退到第一条；删除选中项由 store 乐观移除触发。
import { computed, onMounted, ref, watch } from "vue"
import EmptyState from "../../components/common/EmptyState.vue"
import ErrorState from "../../components/common/ErrorState.vue"
import Skeleton from "../../components/common/Skeleton.vue"
import JobCard from "../../components/domain/JobCard.vue"
import JobDetailPanel from "../../components/domain/JobDetailPanel.vue"
import { JOB_STATUS_LABELS, useJobStore } from "../../stores/job"

const store = useJobStore()

// 筛选 Tab：全部 + 7 个状态（标签取自 JOB_STATUS_LABELS，顺序按 doc 05 状态机）
const FILTERS = [
  { key: "all", label: "全部" },
  ...Object.entries(JOB_STATUS_LABELS).map(([key, label]) => ({ key, label })),
] as const
type FilterKey = (typeof FILTERS)[number]["key"]

const active = ref<FilterKey>("all")

/** 活跃岗位在「全部」视图的置顶顺序（数值越小越靠前） */
const ACTIVE_ORDER: Record<string, number> = {
  chatting: 0,
  applied: 1,
  scored: 2,
  discovered: 3,
}

const displayed = computed(() => {
  if (active.value === "all") {
    return [...store.jobs].sort((a, b) => {
      const diff = (ACTIVE_ORDER[a.status] ?? 9) - (ACTIVE_ORDER[b.status] ?? 9)
      if (diff !== 0) return diff
      return b.updatedAt.localeCompare(a.updatedAt)
    })
  }
  return store.jobs.filter((j) => j.status === active.value)
})

function countByStatus(key: FilterKey): number {
  if (key === "all") return store.jobs.length
  return store.jobs.filter((j) => j.status === key).length
}

const selectedId = ref<number | null>(null)
const selected = computed(() => store.jobs.find((j) => j.id === selectedId.value) ?? null)

// 初始/刷新/删除后自动选中：列表变化时选中项已不存在则回退到第一条
watch(
  () => store.jobs.map((j) => j.id),
  (ids) => {
    if (ids.length === 0) {
      selectedId.value = null
      return
    }
    if (selectedId.value === null || !ids.includes(selectedId.value)) {
      selectedId.value = ids[0]
    }
  },
  { immediate: true },
)

onMounted(() => {
  void store.fetchJobs()
})
</script>

<template>
  <div class="jobs-page">
    <header class="page-head">
      <h2 class="page-title">岗位管理</h2>
      <button type="button" class="refresh-btn" @click="store.fetchJobs()">刷新</button>
    </header>

    <!-- 状态筛选 Tab（样式规范 §33 胶囊选中态；计数仅显示在当前 Tab） -->
    <div class="filter-tabs">
      <button
        v-for="f in FILTERS"
        :key="f.key"
        type="button"
        class="filter-tab"
        :class="{ active: active === f.key }"
        @click="active = f.key"
      >
        {{ f.label }}
        <span v-if="active === f.key && countByStatus(f.key)" class="count">{{ countByStatus(f.key) }}</span>
      </button>
    </div>

    <ErrorState v-if="store.error" :message="`拉取岗位失败：${store.error}`" @retry="store.fetchJobs()" />

    <template v-else>
      <div class="jobs-grid">
        <!-- 左侧：岗位列表（Loading 骨架 / 空态 / 卡片） -->
        <div class="job-list">
          <div v-if="store.loading" class="skeleton-list">
            <Skeleton v-for="i in 4" :key="i" type="card" />
          </div>
          <template v-else>
            <EmptyState
              v-if="!displayed.length"
              title="暂无岗位"
              hint="Agent 寻岗或导入岗位后，最近 10 条会显示在这里"
            />
            <JobCard
              v-for="j in displayed"
              :key="j.id"
              :job="j"
              :active="j.id === selectedId"
              @click="selectedId = j.id"
            />
          </template>
        </div>

        <!-- 右侧：详情面板 -->
        <div class="job-detail-pane">
          <JobDetailPanel :job="selected" />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.jobs-page {
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

.refresh-btn {
  padding: 0 var(--space-4);
  height: 32px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  font-size: var(--fs-secondary);
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast);
}

.refresh-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* 筛选 Tab（样式规范 §33：胶囊选中态） */
.filter-tabs {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-4);
  height: 32px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-pill);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-size: var(--fs-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.filter-tab:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.filter-tab.active {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
}

.count {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--color-danger);
  color: #fff;
  font-size: var(--fs-badge);
  line-height: 18px;
  text-align: center;
}

/* 主从布局：左列表 + 右详情（§19 岗位列表 → 岗位详情） */
.jobs-grid {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}

.job-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.job-detail-pane {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  min-height: 320px;
}
</style>
