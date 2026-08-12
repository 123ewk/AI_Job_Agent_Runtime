<script setup lang="ts">
// 审批 Tab（doc 12 §5.1）：ApprovalList（7 类，含 offsite）+ 倒计时进度条。
// 增量 1：空态占位；增量 4 接 approvalStore（pending 列表 + 20s 倒计时，以 expires_at 为准）。
import EmptyState from "../../components/common/EmptyState.vue"
</script>

<template>
  <EmptyState title="审批" hint="待确认的审批项将在此展示（增量 4 接入）" />
</template>
