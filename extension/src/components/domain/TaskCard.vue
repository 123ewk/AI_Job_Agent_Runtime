<script setup lang="ts">
// 任务卡片（设计权威：前端布局 V1.0 §20，样式规范）。
// 职责：展示单个任务（类型/状态/优先级/时间/进度/错误），支持停止与重试操作。
// 操作直接调 task store（对齐 ApprovalCard 决策模式）：busy 态防重复点击，失败内联展示错误。
import { computed, ref } from "vue"
import StatusBadge from "../common/StatusBadge.vue"
import { formatRelativeTime } from "../../lib/time"
import { TASK_PRIORITY_META, TASK_TYPE_LABELS, type TaskItem } from "../../stores/task"
import { useTaskStore } from "../../stores/task"

const props = defineProps<{ task: TaskItem }>()

const store = useTaskStore()

const typeLabel = computed(() => TASK_TYPE_LABELS[props.task.type] ?? props.task.type)
const priority = computed(
  () =>
    TASK_PRIORITY_META[props.task.priority] ?? {
      label: props.task.priority,
      color: "var(--color-text-secondary)",
    },
)
// 可操作状态：未到终态的任务可停止；失败且未达重试上限可重试
const canCancel = computed(() =>
  ["pending", "running", "waiting_approval", "recovering"].includes(props.task.status),
)
const canRetry = computed(
  () => props.task.status === "failed" && props.task.retryCount < props.task.maxRetries,
)
// 进度条仅在运行中且进度 > 0 时展示
const showProgress = computed(() => props.task.progress > 0 && props.task.status === "running")
const timeText = computed(() => formatRelativeTime(props.task.startedAt ?? props.task.createdAt))

const acting = ref(false)
const actionError = ref<string | null>(null)

async function doAction(action: "cancel" | "retry"): Promise<void> {
  if (acting.value) return
  acting.value = true
  actionError.value = null
  try {
    if (action === "cancel") await store.cancel(props.task)
    else await store.retry(props.task)
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : "操作失败"
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <article class="task-card">
    <header class="card-head">
      <div class="head-left">
        <span class="type-tag">{{ typeLabel }}</span>
        <StatusBadge :status="task.status" />
      </div>
      <span class="priority" :style="{ color: priority.color }">{{ priority.label }}</span>
    </header>

    <p v-if="task.errorMessage" class="error">失败原因：{{ task.errorMessage }}</p>

    <div
      v-if="showProgress"
      class="progress-track"
      role="progressbar"
      :aria-valuenow="task.progress"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <div class="progress-fill" :style="{ width: `${task.progress}%` }"></div>
    </div>
    <p v-if="showProgress" class="progress-label">{{ task.progress }}%</p>

    <footer class="card-foot">
      <span class="time">{{ timeText }}</span>
      <div class="card-actions">
        <button v-if="canRetry" type="button" class="btn" :disabled="acting" @click="doAction('retry')">重试</button>
        <button v-if="canCancel" type="button" class="btn danger" :disabled="acting" @click="doAction('cancel')">
          停止
        </button>
      </div>
    </footer>

    <p v-if="actionError" class="action-error">{{ actionError }}</p>
  </article>
</template>

<style scoped>
.task-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.head-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.type-tag {
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  font-size: var(--fs-aux);
  font-weight: 500;
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.priority {
  flex-shrink: 0;
  font-size: var(--fs-aux);
  font-weight: 600;
}

/* 错误块：danger 色浅底（color-mix 避免硬编码色值） */
.error {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-danger) 8%, transparent);
  color: var(--color-danger);
  font-size: var(--fs-secondary);
  line-height: 1.5;
}

.progress-track {
  height: 6px;
  border-radius: 3px;
  background: var(--color-bg-secondary);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--color-primary);
  transition: width var(--transition-normal);
}

.progress-label {
  margin: 0;
  align-self: flex-end;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.time {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.card-actions {
  display: flex;
  gap: var(--space-2);
}

.btn {
  padding: 0 var(--space-4);
  height: 30px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn.danger {
  border: 1px solid var(--color-danger);
  background: var(--color-bg-card);
  color: var(--color-danger);
}

.btn.danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-danger) 8%, transparent);
}

.btn:not(.danger) {
  border: 1px solid var(--color-border-strong);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
}

.btn:not(.danger):hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.action-error {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--color-danger);
}
</style>
