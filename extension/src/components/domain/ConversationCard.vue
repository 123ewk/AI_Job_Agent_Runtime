<script setup lang="ts">
// 会话列表卡片（设计权威：前端布局 V1.0 §17.1，样式规范）。
// 职责：会话摘要（HR/职位/状态徽章/相对时间）；纯展示，active 高亮由父级传入。
// 说明：根元素是 <button>，父级 @click 会通过属性透传落到按钮上。
import { computed } from "vue"
import { conversationStatusMeta } from "../../lib/statusMeta"
import { formatRelativeTime } from "../../lib/time"
import type { Conversation } from "../../stores/conversation"

const props = defineProps<{
  conversation: Conversation
  active?: boolean
}>()

const title = computed(() => props.conversation.hrName ?? props.conversation.jobTitle ?? "未命名会话")
// 标题已用 HR 姓名时，次行展示职位名；否则次行留空位（避免 title 重复）
const subtitle = computed(() => (props.conversation.hrName ? props.conversation.jobTitle : null))
const status = computed(() => conversationStatusMeta(props.conversation.status))
</script>

<template>
  <button type="button" class="conv-card" :class="{ active }">
    <div class="row">
      <span class="title" :title="title">{{ title }}</span>
      <span class="badge" :style="{ color: status.color, borderColor: status.color }">{{ status.label }}</span>
    </div>
    <div class="row">
      <span class="subtitle" :title="subtitle ?? undefined">{{ subtitle ?? "—" }}</span>
      <span class="time">{{ formatRelativeTime(conversation.updatedAt) }}</span>
    </div>
  </button>
</template>

<style scoped>
.conv-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.conv-card:hover {
  border-color: var(--color-primary);
}

.conv-card.active {
  border-color: var(--color-primary);
  background: var(--color-bg-secondary);
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-width: 0;
}

.title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--color-text-primary);
}

.subtitle {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-secondary);
  color: var(--color-text-secondary);
}

.time {
  flex-shrink: 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.badge {
  flex-shrink: 0;
  padding: 0 6px;
  border: 1px solid;
  border-radius: var(--radius-pill);
  font-size: var(--fs-badge);
  line-height: 18px;
}
</style>
