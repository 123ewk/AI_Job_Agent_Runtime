<script setup lang="ts">
import { onMounted, onUnmounted } from "vue"
import { useAgentStore } from "../stores/agent"
import { useSettingsStore } from "../stores/settings"
import { MessageType } from "../types/messages"
import type { AgentStatusPayload, ApprovalPayload, RuntimeMessage } from "../types/messages"

const agent = useAgentStore()
const settings = useSettingsStore()

function onMessage(msg: unknown): void {
  const message = msg as RuntimeMessage
  switch (message.type) {
    case MessageType.AgentStatusUpdated:
      agent.updateStatus(message.payload as AgentStatusPayload)
      break
    case MessageType.ApprovalRequested:
      agent.pushApproval(message.payload as ApprovalPayload)
      break
    default:
      break
  }
}

onMounted(() => {
  chrome.runtime.onMessage.addListener(onMessage)
})

onUnmounted(() => {
  chrome.runtime.onMessage.removeListener(onMessage)
})
</script>

<template>
  <div class="sidepanel">
    <header>
      <h1>AI 求职 Agent</h1>
      <span class="badge" :class="agent.state">{{ agent.state }}</span>
    </header>

    <section v-if="agent.taskId" class="task">
      <p>任务：{{ agent.taskId }}</p>
      <p v-if="agent.currentNode">节点：{{ agent.currentNode }}</p>
    </section>

    <section v-if="agent.pendingApprovals.length">
      <h3>待确认</h3>
      <div v-for="a in agent.pendingApprovals" :key="a.approvalId" class="approval">
        <p>{{ a.type }}：{{ a.content }}</p>
      </div>
    </section>

    <section class="settings">
      <h3>设置</h3>
      <label><input type="checkbox" v-model="settings.config.autoReply" /> 自动回复</label>
      <label><input type="checkbox" v-model="settings.config.autoApply" /> 自动投递</label>
    </section>
  </div>
</template>

<style scoped>
.sidepanel {
  padding: 16px;
  font-family: system-ui, sans-serif;
}
header {
  display: flex;
  align-items: center;
  gap: 8px;
}
h1 {
  font-size: 16px;
}
h3 {
  font-size: 14px;
  margin: 16px 0 8px;
}
.badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  background: #eee;
}
.badge.running {
  background: #e6f4ff;
  color: #1677ff;
}
.badge.failed {
  background: #fff1f0;
  color: #cf1322;
}
.approval {
  border: 1px solid #eee;
  padding: 8px;
  border-radius: 6px;
  margin: 8px 0;
}
.settings label {
  display: block;
  margin: 4px 0;
}
</style>
