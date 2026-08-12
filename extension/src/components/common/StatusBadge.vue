<script setup lang="ts">
// 状态徽章（doc 12 §6 组件树 common/StatusBadge）。
// 职责：按 §4.3 三态色映射渲染「色点 + 文本」；纯展示组件，props 驱动、无 store 依赖。
// 使用：<StatusBadge :status="'monitoring'" /> 或 <StatusBadge :status="task.status" label="自定义" />
import { computed } from "vue"
import { statusMeta } from "../../lib/statusMeta"
import type { StatusValue } from "../../types/components"

const props = defineProps<{
  /** 三态或 WS 连接态值（doc 12 §4.3 值域） */
  status: StatusValue
  /** 覆盖默认 label（默认取映射表 label） */
  label?: string
}>()

const meta = computed(() => statusMeta(props.status))
</script>

<template>
  <span class="status-badge" :class="{ pulse: meta.pulse }">
    <span class="dot" :style="{ background: meta.color }"></span>
    <span class="text" :style="{ color: meta.color }">{{ label ?? meta.label }}</span>
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.text {
  font-size: var(--fs-aux);
  font-weight: 500;
  line-height: 1;
}

/* 恢复中/重连中的脉冲提示（§4.3 标注 pulse） */
.pulse .dot {
  animation: status-pulse 1.6s ease-in-out infinite;
}

@keyframes status-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}
</style>
