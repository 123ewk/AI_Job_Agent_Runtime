<script setup lang="ts">
// 设置 Tab（doc 12 §5.3）：settings 4 分组表单（llm/agent/job-rule/reply-style）+ 显式保存。
// 增量 1：空态占位；增量 2 接 settingsStore GET/PUT /settings/{group}，并挂载 SettingsPanel.vue（现有本地版）。
import EmptyState from "../../components/common/EmptyState.vue"
</script>

<template>
  <EmptyState title="设置" hint="设置面板将在增量 2 接入后端（GET/PUT /settings/{group}）后启用" />
</template>
