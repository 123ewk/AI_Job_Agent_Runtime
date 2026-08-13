<script setup lang="ts">
// 消息气泡（设计权威：前端布局 V1.0 §17.2/§17.3，样式规范）。
// 职责：按 role 分样式渲染：user 右侧主色 / hr 左侧 / agent 左侧 +「AI Agent」标识 / system 居中细字。
// 设计取舍：agent 消息仅用小标签标识，保持接近真人对话，避免「机器人客服」感（doc §17.2）。
import { computed } from "vue"
import { formatClock } from "../../lib/time"
import type { ChatMessage } from "../../stores/conversation"

const props = defineProps<{ message: ChatMessage }>()

/** 对齐方向：user 右，system 居中，其余左 */
const align = computed<"left" | "right" | "center">(() => {
  if (props.message.role === "user") return "right"
  if (props.message.role === "system") return "center"
  return "left"
})
</script>

<template>
  <!-- system：居中细字提示，无气泡 -->
  <div v-if="message.role === 'system'" class="system">{{ message.content }}</div>

  <div v-else class="row" :class="align">
    <div class="bubble" :class="`role-${message.role}`">
      <span v-if="message.role === 'agent'" class="agent-tag">AI Agent</span>
      <p class="content">{{ message.content }}</p>
      <span class="time">{{ formatClock(message.sentAt) }}</span>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  width: 100%;
}

.row.left {
  justify-content: flex-start;
}

.row.right {
  justify-content: flex-end;
}

/* system 居中提示：无气泡，弱化样式 */
.system {
  align-self: center;
  padding: var(--space-1) var(--space-3);
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.bubble {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 78%;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-card);
  font-size: var(--fs-body);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* user：右侧主色块 */
.role-user {
  background: var(--color-primary);
  color: #ffffff;
}

/* hr / agent：左侧浅灰块（区别于 user） */
.role-hr,
.role-agent {
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  color: var(--color-text-primary);
}

.agent-tag {
  align-self: flex-start;
  padding: 0 6px;
  border-radius: var(--radius-sm);
  background: var(--color-info);
  color: #ffffff;
  font-size: var(--fs-badge);
  font-weight: 500;
  line-height: 18px;
}

.time {
  align-self: flex-end;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.role-user .time {
  color: rgba(255, 255, 255, 0.85);
}
</style>
