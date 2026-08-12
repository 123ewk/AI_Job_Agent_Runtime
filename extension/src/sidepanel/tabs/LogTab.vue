<script setup lang="ts">
// 日志 Tab（doc 12 §5.1/§16）：EventLog（log.appended 流，可按 task 过滤）。
// 增量 1：空态占位；后续接 agentStore.logs 渲染。
import EmptyState from "../../components/common/EmptyState.vue"
</script>

<template>
  <EmptyState title="日志" hint="Agent 运行日志将在此展示（可按任务过滤）" />
</template>
