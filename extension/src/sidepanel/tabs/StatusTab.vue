<script setup lang="ts">
// 状态 Tab（doc 12 §5.1）：AgentStatusCard + TaskCard + 监听控制。
// 增量 1：后端数据未接入，空态占位；增量 2+ 接 agentStore 三态（agent_state/monitoring_state/task.status）。
import EmptyState from "../../components/common/EmptyState.vue"
</script>

<template>
  <EmptyState title="运行状态" hint="接入后端后将在此展示 Agent 状态、当前任务与监听控制" />
</template>
