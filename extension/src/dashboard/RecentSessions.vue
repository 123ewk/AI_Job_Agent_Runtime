<script setup lang="ts">
// 最近会话（设计权威：前端布局 V1.0 §11，样式规范 §20-§22）。
// 列表式（非表格）：Logo + 公司名 + 最新消息 + 时间 + 状态标签。
// 数据：conversation store 为 Phase 2（增量 I8），当前空态 + 引导同步。
import { Building2 } from "lucide-vue-next"
import EmptyState from "../components/common/EmptyState.vue"

defineEmits<{ viewAll: [] }>()

// 占位空态：Phase 2 由 conversation store 驱动
const empty = true
</script>

<template>
  <section class="sessions card">
    <header class="card-head">
      <h3 class="card-title">最近会话</h3>
      <button type="button" class="link-btn" @click="$emit('viewAll')">查看全部 &gt;</button>
    </header>
    <EmptyState v-if="empty" title="暂无会话记录" hint="可点击「立即同步Boss聊天记录」拉取最新消息">
      <button type="button" class="sync-btn">
        <Building2 :size="14" aria-hidden="true" />
        立即同步Boss聊天记录
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

.link-btn {
  border: none;
  background: transparent;
  font-size: var(--fs-secondary);
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: color var(--transition-fast);
}

.link-btn:hover {
  color: var(--color-primary);
}

.sync-btn {
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

.sync-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
</style>
