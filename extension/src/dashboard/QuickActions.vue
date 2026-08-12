<script setup lang="ts">
// 快捷操作（设计权威：前端布局 V1.0 §14，样式规范 §29）。
// 2×3 宫格：图标置顶 + 文字置底；操作项 —— 已接线的跳转路由/打开 Boss，未接线提示 toast。
import { useRouter } from "vue-router"
import { Database, FileDown, Globe, PlusCircle, RefreshCw, SlidersHorizontal } from "lucide-vue-next"
import { useUiStore } from "../stores/ui"
import { useConnectionStore } from "../stores/connection"

const router = useRouter()
const ui = useUiStore()
const connection = useConnectionStore()

const ACTIONS = [
  { key: "new-task", label: "新建任务", icon: PlusCircle, run: () => ui.pushToast("info", "新建任务功能待接线") },
  { key: "sync", label: "手动同步", icon: RefreshCw, run: () => ui.pushToast("info", "手动同步功能待接线") },
  { key: "refresh", label: "刷新数据", icon: Database, run: () => void connection.checkHealth() },
  { key: "boss", label: "打开Boss", icon: Globe, run: () => void chrome.tabs.create({ url: "https://www.zhipin.com/" }) },
  { key: "logs", label: "导出日志", icon: FileDown, run: () => ui.pushToast("info", "导出日志功能待接线") },
  { key: "prefs", label: "设置偏好", icon: SlidersHorizontal, run: () => void router.push("/settings") },
] as const
</script>

<template>
  <section class="quick-actions card">
    <header class="card-head">
      <h3 class="card-title">快捷操作</h3>
    </header>
    <div class="grid">
      <button
        v-for="a in ACTIONS"
        :key="a.key"
        type="button"
        class="action"
        @click="a.run()"
      >
        <component :is="a.icon" class="action-icon" :size="22" aria-hidden="true" />
        <span class="action-label">{{ a.label }}</span>
      </button>
    </div>
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

.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
  margin-top: var(--space-4);
}

/* 操作块（样式规范 §29：78-88px，浅灰底） */
.action {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  height: 80px;
  border: 1px solid transparent;
  border-radius: var(--radius-card);
  background: var(--color-bg-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.action:hover {
  background: #f1f5f9;
  border-color: #d8e2ee;
}

.action-icon {
  color: var(--color-primary);
}

.action-label {
  font-size: var(--fs-aux);
  color: var(--color-text-secondary);
}
</style>
