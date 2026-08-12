<script setup lang="ts">
// 设置分组面板外壳（样式规范 §40 卡片 + §41 按钮）。
// 职责：统一「标题/描述 + 表单槽位 + 底部保存栏」骨架，各分组只关心自身表单字段。
// 保存按钮显式触发（低频修改场景，用户对"何时生效"有明确预期），非自动保存。
defineProps<{
  title: string
  description?: string
  /** 表单相对 store 有未保存修改时可用 */
  dirty: boolean
  saving: boolean
}>()

const emit = defineEmits<{ save: [] }>()
</script>

<template>
  <section class="settings-panel">
    <header class="panel-head">
      <h3 class="panel-title">{{ title }}</h3>
      <p v-if="description" class="panel-desc">{{ description }}</p>
    </header>

    <div class="panel-body"><slot /></div>

    <footer class="panel-foot">
      <span v-if="dirty" class="dirty-hint">有未保存的更改</span>
      <span v-else class="foot-spacer" />
      <button type="button" class="btn-save" :disabled="!dirty || saving" @click="emit('save')">
        {{ saving ? "保存中..." : "保存" }}
      </button>
    </footer>
  </section>
</template>

<style scoped>
.settings-panel {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.panel-head {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.panel-title {
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.panel-desc {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.panel-body {
  padding: var(--space-4) var(--space-5);
}

.panel-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  border-radius: 0 0 var(--radius-card) var(--radius-card);
}

.dirty-hint {
  margin-right: auto;
  font-size: var(--fs-aux);
  color: var(--color-warning);
}

.foot-spacer {
  margin-right: auto;
}

.btn-save {
  padding: 0 var(--space-5);
  height: 32px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  font-size: var(--fs-secondary);
  font-weight: 500;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.btn-save:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.btn-save:disabled {
  background: var(--color-text-disabled);
  cursor: not-allowed;
}
</style>
