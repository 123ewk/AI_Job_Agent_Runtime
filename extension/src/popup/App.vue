<script setup lang="ts">
// Popup 快捷控制（doc 12 §5.2）。
// 增量 1：对齐 Dark token（§4.1）；提供「打开 SidePanel」入口——
//   因为 manifest 设了 default_popup，点击图标只弹 popup、action.onClicked 不触发，
//   background 的 sidePanel.open 路径不可达，故由 popup 用户手势主动打开（doc 12 §5.2 入口）。
// 状态文案暂用 Phase 1 单枚举（types/messages.ts AgentState），三态拆分见后续增量。
import { useAgentStore } from "../stores/agent"

const agent = useAgentStore()

async function openSidePanel(): Promise<void> {
  try {
    // chrome.sidePanel.open 需用户手势 + windowId；当前窗口 active tab 的 windowId 即 popup 所在窗口
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    if (tab?.windowId === undefined) {
      console.warn("[popup] no active tab windowId")
      return
    }
    await chrome.sidePanel.open({ windowId: tab.windowId })
  } catch (err) {
    console.error("[popup] open side panel failed:", err)
  }
}
</script>

<template>
  <div class="popup">
    <h2 class="title">AI 求职 Agent</h2>
    <p class="state">状态：{{ agent.state }}</p>
    <button class="open-btn" @click="openSidePanel">打开 SidePanel ▸</button>
    <p class="hint">完整工作台（6 Tab）在浏览器右侧 SidePanel 中</p>
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
  margin: 0 0 var(--space-3);
  font-size: var(--fs-body);
}

.open-btn {
  width: 100%;
  padding: var(--space-2) 0;
  margin-bottom: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  font-size: var(--fs-body);
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.open-btn:hover {
  background: var(--color-primary-hover);
}

.hint {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--fs-aux);
}
</style>
