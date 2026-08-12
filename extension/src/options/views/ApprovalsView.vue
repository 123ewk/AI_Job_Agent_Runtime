<script setup lang="ts">
// 人工确认页（设计权威：前端布局 V1.0 §21，样式规范 §27-§28）。
// 结构：标题 + 筛选 Tab（全部/待处理/已通过/已拒绝/已超时）+ ApprovalCard 列表。
// 数据：approval store 对接后端（pending 实时拉取）；已通过/已拒绝/已超时无后端接口 → 空态标注（Phase 2 补齐）。
import { onMounted, ref } from "vue"
import EmptyState from "../../components/common/EmptyState.vue"
import ErrorState from "../../components/common/ErrorState.vue"
import ApprovalCard from "../../components/domain/ApprovalCard.vue"
import { useApprovalStore } from "../../stores/approval"

const store = useApprovalStore()

const FILTERS = [
  { key: "pending", label: "待处理" },
  { key: "approved", label: "已通过" },
  { key: "rejected", label: "已拒绝" },
  { key: "timed_out", label: "已超时" },
] as const
type FilterKey = (typeof FILTERS)[number]["key"]

// 「全部」= 待处理；其余状态后端无列表接口（见 store 注释）
const active = ref<FilterKey>("pending")

onMounted(() => {
  void store.refresh()
})
</script>

<template>
  <div class="approvals-page">
    <header class="page-head">
      <h2 class="page-title">人工确认</h2>
      <button type="button" class="refresh-btn" @click="store.refresh()">刷新</button>
    </header>

    <!-- 筛选 Tab（§21：全部/待处理/已通过/已拒绝/已超时） -->
    <div class="filter-tabs">
      <button
        type="button"
        class="filter-tab"
        :class="{ active: active === 'pending' }"
        @click="active = 'pending'"
      >
        全部
      </button>
      <button
        v-for="f in FILTERS"
        :key="f.key"
        type="button"
        class="filter-tab"
        :class="{ active: active === f.key }"
        @click="active = f.key"
      >
        {{ f.label }}
        <span v-if="f.key === 'pending' && store.pending.length" class="count">{{ store.pending.length }}</span>
      </button>
    </div>

    <!-- 仅「待处理」接入后端；历史状态无接口 → 空态标注（Phase 2） -->
    <ErrorState v-if="store.error" :message="`拉取待确认失败：${store.error}`" @retry="store.refresh()" />

    <template v-else-if="active === 'pending'">
      <EmptyState v-if="!store.loading && !store.pending.length" title="暂无待确认事项" hint="涉及薪资/地点/加班等高风险决策时会出现在这里" />
      <div v-else class="approval-list">
        <ApprovalCard v-for="a in store.pending" :key="a.approvalId" :approval="a" />
      </div>
    </template>

    <EmptyState v-else title="暂无历史记录" hint="后端暂未提供审批历史接口，将在 Phase 2 补齐" />
  </div>
</template>

<style scoped>
.approvals-page {
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

.approval-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
</style>
