<script setup lang="ts">
// SidePanel 主壳（doc 12 §5.1）：
//   Header(56px，两行：标题+连接指示 / 监听控制) + TabNav(6 Tab) + 动态 Tab 内容区。
// 职责：壳层，不写业务逻辑；Tab 切换驱动 uiStore.active_tab，组件经 store 单向数据通道。
// 增量 1：无后端/WS，监听控制与连接指示为占位；Port 保活 / 并行 GET / swBridge 订阅在增量 2+ 接入。
import { computed } from "vue"
import type { Component } from "vue"
import { useUiStore } from "../stores/ui"
import ConnectIndicator from "../components/common/ConnectIndicator.vue"
import StatusBadge from "../components/common/StatusBadge.vue"
import Toast from "../components/common/Toast.vue"
import type { TabId } from "../types/components"
import StatusTab from "./tabs/StatusTab.vue"
import TimelineTab from "./tabs/TimelineTab.vue"
import ChatTab from "./tabs/ChatTab.vue"
import ApprovalTab from "./tabs/ApprovalTab.vue"
import LogTab from "./tabs/LogTab.vue"
import SettingsTab from "./tabs/SettingsTab.vue"

const ui = useUiStore()

/** TabNav 项：顺序即展示顺序（doc 12 §5.1） */
const TAB_LIST: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: "status", label: "状态" },
  { id: "timeline", label: "Timeline" },
  { id: "chat", label: "聊天" },
  { id: "approval", label: "审批" },
  { id: "logs", label: "日志" },
  { id: "settings", label: "设置" },
]

/** TabId → 组件映射（动态 <component :is>） */
const TAB_COMPONENTS: Record<TabId, Component> = {
  status: StatusTab,
  timeline: TimelineTab,
  chat: ChatTab,
  approval: ApprovalTab,
  logs: LogTab,
  settings: SettingsTab,
}

const currentTab = computed(() => TAB_COMPONENTS[ui.activeTab])

/**
 * 监听控制占位：增量 1 无后端（写类 Agent 生命周期动作经 swBridge.send 走 SW→REST，
 * doc 12 §8.3）；点击先给占位反馈，避免无响应的假按钮。
 */
function onToggleMonitoring(): void {
  ui.pushToast("info", "监听控制将在后端接线后启用（增量 4+）")
}
</script>

<template>
  <div class="sidepanel">
    <header class="app-header">
      <div class="header-row">
        <div class="brand">AI 求职 Agent</div>
        <ConnectIndicator />
      </div>
      <div class="header-row monitor-row">
        <button class="monitor-btn" @click="onToggleMonitoring">开启监听</button>
        <StatusBadge :status="'idle'" />
      </div>
    </header>

    <nav class="tab-nav" aria-label="主导航">
      <button
        v-for="tab in TAB_LIST"
        :key="tab.id"
        class="tab"
        :class="{ active: ui.activeTab === tab.id }"
        @click="ui.setTab(tab.id)"
      >
        {{ tab.label }}
      </button>
    </nav>

    <main class="tab-content">
      <component :is="currentTab" />
    </main>

    <Toast />
  </div>
</template>

<style scoped>
.sidepanel {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--color-bg);
  color: var(--color-text-primary);
}

/* Header：两行，行高与间距按 doc 12 §5.1（56px 总量级）；
   仅 tab-content 滚动，Header 与 TabNav 固定不滚走。 */
.app-header {
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  padding: var(--space-2) var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  flex-shrink: 0;
}

.header-row {
  display: flex;
  align-items: center;
}

.brand {
  font-size: var(--fs-title);
  font-weight: 600;
  margin-right: auto;
}

/* 监听控制行：按钮 + 监听态徽章（monitoring_state 占位） */
.monitor-row {
  gap: var(--space-2);
}

.monitor-btn {
  padding: var(--space-1) var(--space-3);
  border: none;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  font-size: var(--fs-aux);
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.monitor-btn:hover {
  background: var(--color-primary-hover);
}

/* TabNav */
.tab-nav {
  display: flex;
  flex-shrink: 0;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
}

.tab {
  flex: 1;
  padding: var(--space-2) 0;
  background: none;
  border: none;
  font-size: var(--fs-aux);
  color: var(--color-text-secondary);
  cursor: pointer;
  position: relative;
  transition: color 0.2s;
  white-space: nowrap;
}

.tab:hover {
  color: var(--color-primary-hover);
}

.tab.active {
  color: var(--color-primary);
  font-weight: 500;
}

.tab.active::after {
  content: "";
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 28px;
  height: 2px;
  background: var(--color-primary);
  border-radius: 2px;
}

/* 内容区：独立滚动，不把 Header/TabNav 滚走 */
.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3);
}
</style>
