<!--
  SidePanel 主入口：Tab 式布局（状态 / 设置）。
  职责：展示 Agent 运行状态、任务信息、Approval 待确认项，以及设置面板。
  生命周期：sidepanel 打开时挂载，关闭时卸载；状态通过 chrome.runtime 消息更新。
-->

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue"
import { useAgentStore } from "../stores/agent"
import { useSettingsStore } from "../stores/settings"
import { MessageType } from "../types/messages"
import type {
  AgentStatusPayload,
  ApprovalPayload,
  RuntimeMessage,
  ApprovalDecisionPayload,
} from "../types/messages"
import SettingsPanel from "./SettingsPanel.vue"

const agent = useAgentStore()
const settings = useSettingsStore()

const activeTab = ref<"status" | "settings">("status")

// --- 消息监听 ---

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

// --- Approval 操作 ---

function approve(approvalId: string): void {
  const payload: ApprovalDecisionPayload = { approvalId, decision: "approved" }
  chrome.runtime.sendMessage({
    type: MessageType.ApprovalDecided,
    payload,
  })
  agent.resolveApproval(approvalId)
}

function reject(approvalId: string): void {
  const payload: ApprovalDecisionPayload = { approvalId, decision: "rejected" }
  chrome.runtime.sendMessage({
    type: MessageType.ApprovalDecided,
    payload,
  })
  agent.resolveApproval(approvalId)
}

// --- 状态映射 ---

const stateLabelMap: Record<string, string> = {
  idle: "空闲",
  running: "运行中",
  waiting_approval: "待确认",
  waiting_hr: "等待HR回复",
  completed: "已完成",
  failed: "失败",
}

const stateColorMap: Record<string, string> = {
  idle: "#8c8c8c",
  running: "#1677ff",
  waiting_approval: "#fa8c16",
  waiting_hr: "#722ed1",
  completed: "#52c41a",
  failed: "#cf1322",
}

// --- 生命周期 ---

onMounted(async () => {
  await settings.init()
  chrome.runtime.onMessage.addListener(onMessage)
})

onUnmounted(() => {
  chrome.runtime.onMessage.removeListener(onMessage)
})
</script>

<template>
  <div class="sidepanel">
    <!-- 顶部 Tab 栏 -->
    <nav class="tab-bar">
      <button
        class="tab"
        :class="{ active: activeTab === 'status' }"
        @click="activeTab = 'status'"
      >
        运行状态
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'settings' }"
        @click="activeTab = 'settings'"
      >
        设置
      </button>
    </nav>

    <!-- 状态面板 -->
    <div v-show="activeTab === 'status'" class="panel">
      <!-- Agent 状态卡片 -->
      <section class="card status-card">
        <div class="status-header">
          <span class="status-label">Agent 状态</span>
          <span
            class="status-dot"
            :style="{ background: stateColorMap[agent.state] }"
          ></span>
          <span class="status-text" :style="{ color: stateColorMap[agent.state] }">
            {{ stateLabelMap[agent.state] }}
          </span>
        </div>

        <div v-if="agent.taskId" class="status-detail">
          <div class="detail-row">
            <span class="detail-key">任务 ID</span>
            <span class="detail-value">{{ agent.taskId }}</span>
          </div>
          <div v-if="agent.currentNode" class="detail-row">
            <span class="detail-key">当前节点</span>
            <span class="detail-value">{{ agent.currentNode }}</span>
          </div>
        </div>
        <div v-else class="status-empty">
          当前没有运行中的任务
        </div>
      </section>

      <!-- Approval 待确认 -->
      <section class="card">
        <h3 class="card-title">
          待确认
          <span v-if="agent.pendingApprovals.length" class="badge">
            {{ agent.pendingApprovals.length }}
          </span>
        </h3>

        <div v-if="!agent.pendingApprovals.length" class="empty">
          暂无待确认项
        </div>

        <div
          v-for="approval in agent.pendingApprovals"
          :key="approval.approvalId"
          class="approval-item"
        >
          <div class="approval-type">{{ approval.type }}</div>
          <p class="approval-content">{{ approval.content }}</p>
          <div class="approval-actions">
            <button class="btn btn-approve" @click="approve(approval.approvalId)">
              同意
            </button>
            <button class="btn btn-reject" @click="reject(approval.approvalId)">
              拒绝
            </button>
          </div>
        </div>
      </section>
    </div>

    <!-- 设置面板 -->
    <div v-show="activeTab === 'settings'" class="panel">
      <SettingsPanel />
    </div>
  </div>
</template>

<style scoped>
.sidepanel {
  font-family: system-ui, -apple-system, sans-serif;
  color: #1a1a1a;
  min-height: 100vh;
  background: #fafafa;
}

/* Tab Bar */
.tab-bar {
  display: flex;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
  position: sticky;
  top: 0;
  z-index: 10;
}
.tab {
  flex: 1;
  padding: 12px 0;
  background: none;
  border: none;
  font-size: 13px;
  cursor: pointer;
  color: #595959;
  position: relative;
  transition: color 0.2s;
}
.tab:hover {
  color: #1677ff;
}
.tab.active {
  color: #1677ff;
  font-weight: 500;
}
.tab.active::after {
  content: "";
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 32px;
  height: 2px;
  background: #1677ff;
  border-radius: 2px;
}

.panel {
  padding: 12px;
}

.card {
  background: #fff;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  margin: 0 0 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.badge {
  background: #ff4d4f;
  color: #fff;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  font-weight: 500;
}

/* Status Card */
.status-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.status-label {
  font-size: 13px;
  color: #595959;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-left: auto;
}
.status-text {
  font-size: 13px;
  font-weight: 500;
}
.status-detail {
  border-top: 1px solid #f5f5f5;
  padding-top: 10px;
}
.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 12px;
}
.detail-key {
  color: #8c8c8c;
}
.detail-value {
  color: #262626;
  font-family: monospace;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-empty {
  font-size: 12px;
  color: #bfbfbf;
  text-align: center;
  padding: 12px 0;
}

/* Approval Items */
.empty {
  font-size: 12px;
  color: #bfbfbf;
  text-align: center;
  padding: 16px 0;
}
.approval-item {
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 8px;
}
.approval-item:last-child {
  margin-bottom: 0;
}
.approval-type {
  font-size: 11px;
  font-weight: 600;
  color: #fa8c16;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.approval-content {
  font-size: 12px;
  color: #262626;
  margin: 0 0 10px;
  line-height: 1.5;
}
.approval-actions {
  display: flex;
  gap: 8px;
}
.btn {
  flex: 1;
  padding: 6px 0;
  border: 1px solid transparent;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-approve {
  background: #1677ff;
  color: #fff;
  border-color: #1677ff;
}
.btn-approve:hover {
  background: #0958d9;
}
.btn-reject {
  background: #fff;
  color: #595959;
  border-color: #d9d9d9;
}
.btn-reject:hover {
  color: #cf1322;
  border-color: #ffa39e;
}
</style>
