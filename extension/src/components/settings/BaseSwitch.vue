<script setup lang="ts">
// 设置页共享开关（样式规范 §7：44×24 胶囊，开启品牌蓝）。
// v-model 驱动的受控组件，杜绝各面板重复实现 switch 样式。
defineProps<{ label: string; hint?: string }>()
const model = defineModel<boolean>({ required: true })
</script>

<template>
  <div class="switch-row">
    <div class="switch-info">
      <span class="switch-label">{{ label }}</span>
      <span v-if="hint" class="switch-hint">{{ hint }}</span>
    </div>
    <button
      type="button"
      class="switch"
      :class="{ on: model }"
      role="switch"
      :aria-checked="model"
      :aria-label="label"
      @click="model = !model"
    >
      <span class="knob" />
    </button>
  </div>
</template>

<style scoped>
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-2) 0;
}

.switch-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.switch-label {
  font-size: var(--fs-body);
  font-weight: 500;
  color: var(--color-text-primary);
}

.switch-hint {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.switch {
  position: relative;
  flex-shrink: 0;
  width: 44px;
  height: 24px;
  border: none;
  border-radius: var(--radius-pill);
  background: var(--color-border-strong);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.switch.on {
  background: var(--color-primary);
}

.knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #ffffff;
  transition: transform var(--transition-fast);
}

.switch.on .knob {
  transform: translateX(20px);
}
</style>
