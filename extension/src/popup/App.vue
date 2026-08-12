<script setup lang="ts">
// Popup 快捷控制（doc 12 §5.2 最小版）。
// 增量 1：对齐 Dark token（§4.1）；无后端/WS，监听/审批入口留后续增量。
// 状态文案暂用 Phase 1 单枚举（types/messages.ts AgentState），三态拆分见后续增量。
import { useAgentStore } from "../stores/agent"

const agent = useAgentStore()
</script>

<template>
  <div class="popup">
    <h2 class="title">AI 求职 Agent</h2>
    <p class="state">状态：{{ agent.state }}</p>
    <p class="hint">点击扩展图标在 SidePanel 中查看详情</p>
  </div>
</template>

<style scoped>
.popup {
  padding: var(--space-3);
  min-width: 240px;
  background: var(--color-bg);
  color: var(--color-text-primary);
}

.title {
  margin: 0 0 var(--space-2);
  font-size: var(--fs-title);
}

.state {
  margin: 0 0 var(--space-1);
  font-size: var(--fs-body);
}

.hint {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--fs-aux);
}
</style>
