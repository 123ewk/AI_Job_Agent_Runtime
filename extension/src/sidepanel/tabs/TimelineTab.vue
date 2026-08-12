<script setup lang="ts">
// Timeline Tab（doc 12 §5.1）：Timeline（agent.step / tool.call 时序流）。
// 增量 1：空态占位；后续经 agentStore.timeline_events 渲染。
import EmptyState from "../../components/common/EmptyState.vue"
</script>

<template>
  <EmptyState title="时间线" hint="Agent 执行步骤与工具调用的时序将在此展示" />
</template>
