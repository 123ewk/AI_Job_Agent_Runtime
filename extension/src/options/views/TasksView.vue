<script setup lang="ts">
// 任务中心页（设计权威：前端布局 V1.0 §20，样式规范）。
// 结构：状态筛选 Tab + TaskCard 列表。
// 数据：task store 拉全量后客户端筛选（各 Tab 计数准确 + 切换即时）。
// 设计取舍：doc §20 强调「当前任务 + 等待队列」（系统不允许多任务并发）；
//   「全部」视图按活跃状态排序（running/waiting_approval/recovering/pending 置顶）近似该结构。
import { computed, onMounted, ref } from "vue"
import EmptyState from "../../components/common/EmptyState.vue"
import ErrorState from "../../components/common/ErrorState.vue"
import TaskCard from "../../components/domain/TaskCard.vue"
import { useTaskStore } from "../../stores/task"

const store = useTaskStore()

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "pending", label: "等待" },
  { key: "running", label: "运行中" },
  { key: "waiting_approval", label: "待确认" },
  { key: "recovering", label: "恢复中" },
  { key: "succeeded", label: "成功" },
  { key: "failed", label: "失败" },
  { key: "canceled", label: "已取消" },
] as const
type FilterKey = (typeof FILTERS)[number]["key"]

const active = ref<FilterKey>("all")

/** 活跃任务在「全部」视图的置顶顺序（数值越小越靠前） */
const ACTIVE_ORDER: Record<string, number> = {
  running: 0,
  waiting_approval: 1,
  recovering: 2,
  pending: 3,
}

const displayed = computed(() => {
  if (active.value === "all") {
    return [...store.tasks].sort((a, b) => {
      const diff = (ACTIVE_ORDER[a.status] ?? 9) - (ACTIVE_ORDER[b.status] ?? 9)
      if (diff !== 0) return diff
      return b.createdAt.localeCompare(a.createdAt)
    })
  }
  return store.tasks.filter((t) => t.status === active.value)
})

function countByStatus(key: FilterKey): number {
  if (key === "all") return store.tasks.length
  return store.tasks.filter((t) => t.status === key).length
}

onMounted(() => {
  void store.fetchTasks()
})
</script>

<template>
  <div class="tasks-page">
    <header class="page-head">
      <h2 class="page-title">任务中心</h2>
      <button type="button" class="refresh-btn" @click="store.fetchTasks()">刷新</button>
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

    <ErrorState v-if="store.error" :message="`拉取任务失败：${store.error}`" @retry="store.fetchTasks()" />

    <template v-else>
      <EmptyState v-if="!store.loading && !displayed.length" title="暂无任务" hint="Agent 执行任务时会实时出现在这里" />
      <div v-else class="task-list">
        <TaskCard v-for="t in displayed" :key="t.id" :task="t" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.tasks-page {
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

.task-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
</style>
