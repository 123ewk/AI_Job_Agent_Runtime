<script setup lang="ts">
import { useAgentStore } from "../stores/agent"

const agent = useAgentStore()
</script>

<template>
  <div class="popup">
    <h2>AI 求职 Agent</h2>
    <p>状态：{{ agent.state }}</p>
    <p class="hint">点击扩展图标在 SidePanel 中查看详情</p>
  </div>
</template>

<style scoped>
.popup {
  padding: 12px;
  min-width: 240px;
  font-family: system-ui, sans-serif;
}
.hint {
  color: #888;
  font-size: 12px;
}
</style>
