<script setup lang="ts">
// 错误状态（doc 12 §4.2 / §13：错误说明 + trace_id + 重试按钮）。
// 纯展示组件；retry 事件由父级决定重试逻辑（前端不自动重试业务失败，doc 12 §14）。
defineProps<{
  message: string
  /** 后端下发的 trace_id，便于排查 */
  traceId?: string
}>()

defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="error-state">
    <p class="message">{{ message }}</p>
    <p v-if="traceId" class="trace">trace_id: {{ traceId }}</p>
    <button class="retry-btn" @click="$emit('retry')">重试</button>
  </div>
</template>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-6) var(--space-4);
  text-align: center;
}

.message {
  margin: 0;
  font-size: var(--fs-body);
  color: var(--color-error);
}

.trace {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--color-text-secondary);
  font-family: monospace;
}

.retry-btn {
  margin-top: var(--space-2);
  padding: var(--space-1) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text-primary);
  font-size: var(--fs-aux);
  cursor: pointer;
  transition: border-color 0.2s;
}

.retry-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
</style>
