<script setup lang="ts">
// 任务进度（设计权威：前端布局 V1.0 §12，样式规范 §23）。
// 任务列表：图标 + 名称 + 说明 + 进度条 + 状态。
// 数据：task store 为 Phase 2（增量 I9），当前空态占位。
import { CheckCircle2 } from "lucide-vue-next"
import EmptyState from "../components/common/EmptyState.vue"

// 占位空态：Phase 2 由 task store 驱动
const empty = true
</script>

<template>
  <section class="tasks card">
    <header class="card-head">
      <h3 class="card-title">任务进度</h3>
    </header>
    <EmptyState v-if="empty" title="暂无进行中的任务" hint="新建任务后在此查看执行进度">
      <button type="button" class="new-btn">
        <CheckCircle2 :size="14" aria-hidden="true" />
        新建任务
      </button>
    </EmptyState>
  </section>
</template>

<style scoped>
.card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: var(--space-5);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.new-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-size: var(--fs-aux);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.new-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
</style>
