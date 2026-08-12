<script setup lang="ts">
// 连接指示（doc 12 §4.2 / §9.3：Header 常驻；绿 connected / 黄 reconnecting / 红 disconnected）。
// 增量 1 无 WS 接线，state 默认 disconnected；后续增量由 agentStore.ws_state 驱动。
import { computed } from "vue"
import { statusMeta } from "../../lib/statusMeta"
import type { WsState } from "../../types/components"

const props = withDefaults(defineProps<{ state?: WsState }>(), { state: "disconnected" })

const meta = computed(() => statusMeta(props.state))

const tip = computed(() => {
  switch (props.state) {
    case "connected":
      return "已连接后端"
    case "reconnecting":
      return "重连中，事件可能延迟"
    case "disconnected":
      return "未连接后端"
  }
})
</script>

<template>
  <span class="connect-indicator" :title="tip">
    <span class="dot" :class="props.state" :style="{ background: meta.color }"></span>
    <span class="label" :style="{ color: meta.color }">{{ meta.label }}</span>
  </span>
</template>

<style scoped>
.connect-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: default;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

/* 重连脉冲提示（doc 12 §4.3 reconnecting pulse） */
.dot.reconnecting {
  animation: connect-pulse 1.6s ease-in-out infinite;
}

.label {
  font-size: var(--fs-aux);
  font-weight: 500;
}

@keyframes connect-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}
</style>
