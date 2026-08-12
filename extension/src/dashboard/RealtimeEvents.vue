<script setup lang="ts">
// 实时事件（设计权威：前端布局 V1.0 §10，样式规范 §24-§26）。
// Timeline：时间胶囊 + 事件标题 + 描述 + 等级色圆点。右上「清空」。
// 数据：事件结构见 V1.0 §52（event_id/event_type/timestamp/...），当前空态，
//       Phase 2 由 WS 事件流驱动（后端 WS 为 stub）。
import EmptyState from "../components/common/EmptyState.vue"

// 事件等级 → 色点（样式规范 §26）
// 占位空态：Phase 2 由 WS 事件流驱动
const empty = true
</script>

<template>
  <section class="events card">
    <header class="card-head">
      <h3 class="card-title">实时事件</h3>
      <button type="button" class="clear-btn" :disabled="empty">清空</button>
    </header>
    <EmptyState v-if="empty" title="暂无实时事件" hint="Agent 执行操作时事件将实时显示在这里" />
  </section>
</template>

<style scoped>
.card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: var(--space-5);
  height: 100%;
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

.clear-btn {
  border: none;
  background: transparent;
  font-size: var(--fs-secondary);
  color: var(--color-text-tertiary);
  cursor: pointer;
}

.clear-btn:disabled {
  cursor: default;
  color: var(--color-text-disabled);
}
</style>
