<script setup lang="ts">
// 日志与事件页（设计权威：前端布局 V1.0 §22，样式规范 §24-§26）。
// 结构：默认时间线视图（时间/事件/结果）+ 高级模式开关（Task ID/Conversation ID/Trace ID/原始 type）。
// 数据：event store 经 WebSocket 接收后端实时事件（后端 emit_* 为 stub，实际仅连接事件）。
// 已知缺口：后端 WS 事件推送为 stub（memory phase2-progress 风险 2），接线后本页实时驱动。
// 注：WS 连接生命周期由 DashboardLayout 统一持有（布局级 connect/disconnect），
//   本页不做 connect/unmount disconnect，避免离开本页时把共享事件连接一并关闭。
import { ref } from "vue"
import EmptyState from "../../components/common/EmptyState.vue"
import EventTimeline from "../../components/common/EventTimeline.vue"
import { useEventStore } from "../../stores/events"

const store = useEventStore()
const advanced = ref(false)
</script>

<template>
  <div class="logs-page">
    <header class="page-head">
      <h2 class="page-title">日志与事件</h2>
      <div class="head-actions">
        <label class="adv-switch">
          <input v-model="advanced" type="checkbox" class="adv-input" />
          <span class="adv-label">高级模式</span>
        </label>
        <button
          type="button"
          class="refresh-btn"
          :disabled="store.wsState === 'connected'"
          @click="store.connect()"
        >
          {{ store.wsState === "connected" ? "已连接" : store.wsState === "reconnecting" ? "重连中…" : "连接" }}
        </button>
        <button type="button" class="refresh-btn" :disabled="!store.events.length" @click="store.clear()">清空</button>
      </div>
    </header>

    <p v-if="store.wsState !== 'connected'" class="conn-hint">
      事件流未连接（后端 WS 当前为 stub，仅连接成功时收到 system.connected）。
    </p>

    <EmptyState v-if="!store.events.length" title="暂无事件" hint="Agent 执行操作时事件将实时显示在这里" />
    <EventTimeline v-else :events="store.events" :advanced="advanced" />
  </div>
</template>

<style scoped>
.logs-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.page-title {
  margin: 0;
  font-size: var(--fs-page-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
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

.refresh-btn:hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.refresh-btn:disabled {
  color: var(--color-text-disabled);
  cursor: default;
}

/* 高级模式开关（checkbox 驱动） */
.adv-switch {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}

.adv-input {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary);
  cursor: pointer;
}

.adv-label {
  font-size: var(--fs-secondary);
  color: var(--color-text-secondary);
}

.conn-hint {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}
</style>
