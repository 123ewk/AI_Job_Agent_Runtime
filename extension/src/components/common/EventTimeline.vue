<script setup lang="ts">
// 事件时间线（设计权威：前端布局 V1.0 §22/§52，样式规范 §24-§26）。
// 职责：渲染事件列表（时间/事件/结果 + 等级色点 + 描述 + 高级模式 meta）。
// 说明：被 LogsView（默认+高级模式）与 Overview 实时事件卡（limit）复用；纯展示，无 store 依赖。
import { computed } from "vue"
import { formatClock, formatDate } from "../../lib/time"
import type { EventLogItem } from "../../stores/events"

const props = defineProps<{
  events: EventLogItem[]
  /** 显示条数上限（Dashboard 实时事件卡常用） */
  limit?: number
  /** 高级模式：额外展示 task_id / conversation_id / trace_id / eventType */
  advanced?: boolean
}>()

const LEVEL_COLORS: Record<string, string> = {
  danger: "var(--color-danger)",
  warning: "var(--color-warning)",
  info: "var(--color-info)",
  success: "var(--color-success)",
  muted: "var(--color-text-disabled)",
}

const LEVEL_LABELS: Record<string, string> = {
  danger: "失败",
  warning: "待确认",
  info: "进行中",
  success: "成功",
  muted: "—",
}

const shown = computed(() => props.events.slice(0, props.limit ?? props.events.length))
</script>

<template>
  <ol class="timeline">
    <li v-for="ev in shown" :key="ev.id" class="item">
      <span class="dot" :style="{ background: LEVEL_COLORS[ev.level] ?? LEVEL_COLORS.muted }"></span>
      <div class="body">
        <div class="line">
          <span class="time">{{ formatClock(ev.ts) }}</span>
          <span class="title">{{ ev.title }}</span>
          <span class="result" :style="{ color: LEVEL_COLORS[ev.level] ?? LEVEL_COLORS.muted }">
            {{ LEVEL_LABELS[ev.level] ?? ev.level }}
          </span>
        </div>
        <p class="desc">{{ ev.description }}</p>
        <p v-if="advanced" class="meta">
          <span v-if="ev.taskId !== null">Task {{ ev.taskId }}</span>
          <span v-if="ev.conversationId !== null">Conv {{ ev.conversationId }}</span>
          <span v-if="ev.traceId">Trace {{ ev.traceId }}</span>
          <span>{{ ev.eventType }}</span>
          <span>{{ formatDate(ev.ts) }}</span>
        </p>
      </div>
    </li>
  </ol>
</template>

<style scoped>
.timeline {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.item {
  display: flex;
  gap: var(--space-3);
}

/* 等级色点（样式规范 §26） */
.dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
}

.body {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.line {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.time {
  flex-shrink: 0;
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  color: var(--color-text-tertiary);
}

.title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body);
  font-weight: 500;
  color: var(--color-text-primary);
}

.result {
  flex-shrink: 0;
  margin-left: auto;
  font-size: var(--fs-aux);
  font-weight: 500;
}

.desc {
  margin: 0;
  font-size: var(--fs-secondary);
  line-height: 1.5;
  color: var(--color-text-secondary);
  word-break: break-word;
}

/* 高级模式 meta（§22：Task ID/Conversation ID/Trace ID/Error） */
.meta {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  color: var(--color-text-tertiary);
}

.meta span {
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
}
</style>
