<script setup lang="ts">
// 骨架屏（doc 12 §4.2：Loading 禁转圈，用骨架屏/状态文案占位）。
// 纯展示组件：type="card" 生成卡片块，type="line" 生成文本行。
defineProps<{
  /** 骨架形态：card 卡片 / line 文本行 */
  type?: "card" | "line"
  /** line 形态下的文本行数 */
  rows?: number
}>()
</script>

<template>
  <div class="skeleton" :class="type ?? 'card'">
    <template v-if="(type ?? 'card') === 'card'">
      <div class="skeleton-card">
        <div class="skeleton-line short" />
        <div class="skeleton-line" />
        <div class="skeleton-line" />
      </div>
    </template>
    <template v-else>
      <div v-for="i in rows ?? 3" :key="i" class="skeleton-line" :class="{ short: i % 2 === 0 }" />
    </template>
  </div>
</template>

<style scoped>
/* 呼吸闪烁替代转圈 */
.skeleton-card,
.skeleton-line {
  background: var(--color-surface);
  border-radius: var(--radius-sm);
  animation: skeleton-breathe 1.4s ease-in-out infinite;
}

.skeleton-card {
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.skeleton-line {
  height: 12px;
  border-radius: 999px;
}

.skeleton-line.short {
  width: 60%;
}

.skeleton.line .skeleton-line {
  margin-bottom: var(--space-2);
}

@keyframes skeleton-breathe {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}
</style>
