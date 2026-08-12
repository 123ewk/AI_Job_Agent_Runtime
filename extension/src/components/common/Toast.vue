<script setup lang="ts">
// 全局通知（doc 12 §4.2：右上角，2-3s 自动消失；成功绿/错误红/信息主色）。
// 经 Teleport 挂到 body 顶部，避免被 SidePanel 的 overflow 滚动裁剪。
// 队列由 uiStore 管理（pushToast/dismissToast + setTimeout 自动消失），组件只渲染。
import { useUiStore } from "../../stores/ui"

const ui = useUiStore()
</script>

<template>
  <Teleport to="body">
    <div v-if="ui.toasts.length" class="toast-container" role="status" aria-live="polite">
      <TransitionGroup name="toast">
        <div v-for="toast in ui.toasts" :key="toast.id" class="toast" :class="toast.kind">
          {{ toast.message }}
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-container {
  position: fixed;
  top: var(--space-3);
  right: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  z-index: 999;
  pointer-events: none;
}

.toast {
  max-width: 300px;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  color: var(--color-text-primary);
  font-size: var(--fs-aux);
  box-shadow: var(--shadow-dropdown);
}

/* 语义色左边条区分种类 */
.toast.success {
  border-left: 3px solid var(--color-success);
}

.toast.error {
  border-left: 3px solid var(--color-danger);
}

.toast.info {
  border-left: 3px solid var(--color-primary);
}

/* 入/退场过渡（doc 12 §4.2 微动效） */
.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(12px);
}
</style>
