<script setup lang="ts">
// 聊天 Tab（doc 12 §5.1）：ConversationList + ChatPanel + MessageInput。
// 增量 1：空态占位；增量 3 接 conversationStore（乐观更新 + WS 确认）。
import EmptyState from "../../components/common/EmptyState.vue"
</script>

<template>
  <EmptyState title="聊天" hint="与 HR 的对话与消息将在此展示（增量 3 接入）" />
</template>
