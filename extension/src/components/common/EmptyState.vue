<script setup lang="ts">
// 空状态（doc 12 §4.2 EmptyState：图标 + 一句话 + 引导动作）。
// 纯展示组件；可通过默认插槽放入引导按钮等动作。
defineProps<{
  title: string
  /** 补充说明（可提示下一步） */
  hint?: string
}>()
</script>

<template>
  <div class="empty-state">
    <div class="icon" aria-hidden="true">◇</div>
    <p class="title">{{ title }}</p>
    <p v-if="hint" class="hint">{{ hint }}</p>
    <div class="action"><slot /></div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-6) var(--space-4);
  text-align: center;
  color: var(--color-text-secondary);
}

.icon {
  font-size: 28px;
  color: var(--color-border);
  line-height: 1;
}

.title {
  margin: 0;
  font-size: var(--fs-body);
  font-weight: 500;
  color: var(--color-text-primary);
}

.hint {
  margin: 0;
  font-size: var(--fs-aux);
  line-height: 1.5;
}

.action {
  margin-top: var(--space-2);
}
</style>
