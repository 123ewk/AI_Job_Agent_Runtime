<script setup lang="ts">
// Popup 快捷控制（设计权威：前端布局 V1.0 §34，样式规范 §47 窄屏模式）。
// 结构：Agent 状态 + 自动回复/自动投递/后台监听 3 开关 + 当前任务 + 打开控制台/立即同步。
// 3 开关写 chrome.storage.local（跨上下文同步，background 消费）；不复制完整 Dashboard（§34）。
// 额外保留「打开 SidePanel」入口：default_popup 使 action.onClicked 不触发，只能由 popup 用户手势打开。
import { onMounted, onUnmounted, ref } from "vue"
import { Bot, ClipboardCopy, PanelRight, Plug, RefreshCw } from "lucide-vue-next"
import StatusBadge from "../components/common/StatusBadge.vue"
import { useAgentStore } from "../stores/agent"
import { useConnectionStore } from "../stores/connection"
import { useUiStore } from "../stores/ui"
import { apiGet } from "../lib/api"

const agent = useAgentStore()
const connection = useConnectionStore()
const ui = useUiStore()

// ---------------------------------------------------------------------------
// 浏览器桥（Chrome MCP Server /ws 通道）状态 —— 对齐 17-ChromeMCPServer落地选型
// background/bridge/websocketClient.ts 持有真实连接，popup 经 runtime 消息查询/控制。
// ---------------------------------------------------------------------------
type BridgeState = "connected" | "reconnecting" | "disconnected" | "no_token"

const bridgeState = ref<BridgeState>("disconnected")
const bridgeToken = ref("")

async function refreshBridgeState(): Promise<void> {
  try {
    const resp = await chrome.runtime.sendMessage({ type: "getBridgeState" })
    bridgeState.value = !resp?.hasToken
      ? "no_token"
      : resp?.connected
        ? "connected"
        : "reconnecting"
  } catch {
    bridgeState.value = "disconnected"
  }
}

async function loadBridgeToken(): Promise<void> {
  const { browser_mcp_token } = await chrome.storage.local.get("browser_mcp_token")
  bridgeToken.value = (browser_mcp_token as string | undefined) ?? ""
}

function saveBridgeToken(): void {
  void chrome.runtime.sendMessage({ type: "setBridgeToken", token: bridgeToken.value.trim() })
  ui.pushToast("success", "浏览器桥令牌已保存")
}

/**
 * 一键获取令牌：调后端 GET /api/v1/browser/token（与 mcp-server 同源 secrets 文件），
 * 自动填入输入框并保存。免除手动复制粘贴。
 */
async function fetchBridgeToken(): Promise<void> {
  try {
    const data = await apiGet<{ token: string }>("/browser/token")
    if (!data.token) {
      ui.pushToast("error", "后端未读到令牌：先启动 mcp-server 或配置 BROWSER_MCP_TOKEN")
      return
    }
    bridgeToken.value = data.token
    void chrome.runtime.sendMessage({ type: "setBridgeToken", token: data.token })
    ui.pushToast("success", "已自动获取并保存令牌")
    await refreshBridgeState()
  } catch (err) {
    ui.pushToast("error", `获取令牌失败：${err instanceof Error ? err.message : String(err)}（后端在跑吗？）`)
  }
}

function reconnectBridge(): void {
  void chrome.runtime.sendMessage({ type: "bridgeConnect" })
  void refreshBridgeState()
}

const BRIDGE_STATE_LABEL: Record<BridgeState, string> = {
  connected: "已连接",
  reconnecting: "连接中…",
  disconnected: "未连接",
  no_token: "未配置令牌",
}

// 监听 background 广播的状态变更（bridge/websocketClient broadcastState）
const onBridgeBroadcast = (message: unknown): void => {
  const msg = message as { type?: string; payload?: { connected?: boolean; hasToken?: boolean } }
  if (msg?.type === "BRIDGE_STATE_CHANGED") {
    bridgeState.value = !msg.payload?.hasToken
      ? "no_token"
      : msg.payload?.connected
        ? "connected"
        : "reconnecting"
  }
}

onMounted(async () => {
  await loadBridgeToken()
  await refreshBridgeState()
  const stored = await chrome.storage.local.get(PREFS_KEY)
  prefs.value = { ...prefs.value, ...(stored[PREFS_KEY] as Partial<PopupPrefs> | undefined) }
  chrome.runtime.onMessage.addListener(onBridgeBroadcast)
})

onUnmounted(() => {
  chrome.runtime.onMessage.removeListener(onBridgeBroadcast)
})

/** 3 开关的持久化偏好（写 chrome.storage.local，key 独立于 app_settings） */
interface PopupPrefs {
  autoReply: boolean
  autoApply: boolean
  backgroundListen: boolean
}

const PREFS_KEY = "popup_prefs"

/** 3 开关展示项（key 对应 PopupPrefs 字段） */
const SWITCH_ITEMS: { key: keyof PopupPrefs; label: string }[] = [
  { key: "autoReply", label: "自动回复" },
  { key: "autoApply", label: "自动投递" },
  { key: "backgroundListen", label: "后台监听" },
]

const prefs = ref<PopupPrefs>({ autoReply: false, autoApply: false, backgroundListen: false })

onMounted(async () => {
  const stored = await chrome.storage.local.get(PREFS_KEY)
  prefs.value = { ...prefs.value, ...(stored[PREFS_KEY] as Partial<PopupPrefs> | undefined) }
})

function toggle(key: keyof PopupPrefs): void {
  prefs.value[key] = !prefs.value[key]
  // 写入后触发 chrome.storage.onChanged，各上下文可监听同步
  void chrome.storage.local.set({ [PREFS_KEY]: prefs.value })
}

/** 状态文案：优先监听态，否则回退运行态（与 AgentStatusCard 语义一致） */
const statusText = (): string => {
  if (agent.monitoring === "monitoring") return "监听中"
  if (agent.monitoring === "paused") return "已暂停"
  if (agent.monitoring === "stopped") return "已停止"
  return "空闲"
}

function openDashboard(): void {
  void chrome.runtime.openOptionsPage()
}

async function openSidePanel(): Promise<void> {
  try {
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

async function syncNow(): Promise<void> {
  await connection.checkHealth()
  if (connection.state === "connected") {
    ui.pushToast("success", "同步完成，连接正常")
  } else {
    ui.pushToast("error", "同步失败：后端未连接")
  }
}
</script>

<template>
  <div class="popup">
    <!-- Header：品牌 + 状态（§34） -->
    <header class="popup-header">
      <div class="brand">
        <Bot :size="20" class="brand-logo" aria-hidden="true" />
        <span class="brand-name">AI求职Agent</span>
      </div>
      <div class="status">
        <StatusBadge :status="agent.uiStatus" />
        <span class="status-text">{{ statusText() }}</span>
      </div>
    </header>

    <!-- 3 个快捷开关（§34） -->
    <div class="switch-list">
      <div v-for="item in SWITCH_ITEMS" :key="item.key" class="switch-row">
        <span class="switch-label">{{ item.label }}</span>
        <button
          type="button"
          class="switch"
          :class="{ on: prefs[item.key] }"
          role="switch"
          :aria-checked="prefs[item.key]"
          @click="toggle(item.key)"
        >
          <span class="knob" />
        </button>
      </div>
    </div>

    <!-- 浏览器桥（Chrome MCP Server /ws 通道） -->
    <div class="bridge-card">
      <div class="bridge-head">
        <span class="bridge-title"><Plug :size="14" /> 浏览器桥</span>
        <span class="bridge-state" :class="bridgeState">
          <span class="dot" />{{ BRIDGE_STATE_LABEL[bridgeState] }}
        </span>
      </div>
      <div class="bridge-token">
        <input
          v-model="bridgeToken"
          type="text"
          spellcheck="false"
          placeholder="粘贴 mcp-server token（node mcp-server/token.js --print）"
          class="token-input"
        />
        <button type="button" class="mini-btn" title="从后端自动获取令牌（需后端运行中）" @click="fetchBridgeToken">
          <ClipboardCopy :size="13" /> 获取
        </button>
        <button type="button" class="mini-btn" :disabled="!bridgeToken.trim()" @click="saveBridgeToken">
          保存
        </button>
        <button type="button" class="mini-btn" :disabled="bridgeState === 'connected'" @click="reconnectBridge">
          重连
        </button>
      </div>
    </div>

    <!-- 当前任务（§34） -->
    <div class="task-card">
      <p class="task-label">当前任务</p>
      <p class="task-value">{{ agent.currentTask ?? "Agent 待机中" }}</p>
    </div>

    <!-- 主操作：打开控制台 + 立即同步（§34） -->
    <div class="actions">
      <button type="button" class="btn primary" @click="openDashboard">打开控制台</button>
      <button type="button" class="btn" @click="syncNow"><RefreshCw :size="14" /> 立即同步</button>
    </div>

    <!-- 保留 SidePanel 入口（I4 决定：default_popup 使 action.onClicked 不可达） -->
    <button type="button" class="side-link" @click="openSidePanel">
      <PanelRight :size="14" />
      打开 SidePanel
    </button>
  </div>
</template>

<style scoped>
.popup {
  width: 360px;
  padding: var(--space-4);
  background: var(--color-bg-page);
  color: var(--color-text-primary);
  font-family: var(--font-sans);
}

/* Header（§34：品牌 + 状态） */
.popup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.brand-logo {
  color: var(--color-primary);
}

.brand-name {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--color-text-primary);
}

.status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.status-text {
  font-size: var(--fs-secondary);
  color: var(--color-text-secondary);
}

/* 3 开关（样式规范 §7：44×24 胶囊，开启品牌蓝） */
.switch-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  transition: background var(--transition-fast);
}

.switch-row:hover {
  background: var(--color-bg-card);
}

.switch-label {
  font-size: var(--fs-body);
  color: var(--color-text-primary);
}

.switch {
  position: relative;
  width: 44px;
  height: 24px;
  border: none;
  border-radius: var(--radius-pill);
  background: var(--color-border-strong);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.switch.on {
  background: var(--color-primary);
}

.knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #ffffff;
  transition: transform var(--transition-fast);
}

.switch.on .knob {
  transform: translateX(20px);
}

/* 浏览器桥卡片 */
.bridge-card {
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

.bridge-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.bridge-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-aux);
  color: var(--color-text-secondary);
}

.bridge-state {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.bridge-state .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-border-strong);
}

.bridge-state.connected .dot {
  background: var(--color-success, #22c55e);
}

.bridge-state.connected {
  color: var(--color-success, #22c55e);
}

.bridge-state.reconnecting .dot {
  background: #f59e0b;
}

.bridge-state.reconnecting {
  color: #f59e0b;
}

.bridge-state.no_token .dot {
  background: #ef4444;
}

.bridge-state.no_token {
  color: #ef4444;
}

.bridge-token {
  display: flex;
  gap: var(--space-1);
}

.token-input {
  flex: 1;
  min-width: 0;
  height: 28px;
  padding: 0 var(--space-2);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-bg-page);
  color: var(--color-text-primary);
  font-size: var(--fs-aux);
}

.mini-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 28px;
  padding: 0 var(--space-2);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-size: var(--fs-aux);
  cursor: pointer;
  white-space: nowrap;
}

.mini-btn:hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.mini-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 当前任务（§34） */
.task-card {
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

.task-label {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.task-value {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-body);
  font-weight: 500;
  color: var(--color-text-primary);
}

/* 主操作（§34：打开控制台 + 立即同步） */
.actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  margin-top: var(--space-3);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  height: 36px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-secondary);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn.primary {
  border: none;
  background: var(--color-primary);
  color: #fff;
}

.btn.primary:hover {
  background: var(--color-primary-hover);
}

.btn:not(.primary) {
  border: 1px solid var(--color-border-strong);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
}

.btn:not(.primary):hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* SidePanel 入口（次级链接） */
.side-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  width: 100%;
  margin-top: var(--space-2);
  padding: var(--space-2) 0;
  border: none;
  background: transparent;
  color: var(--color-text-tertiary);
  font-size: var(--fs-aux);
  cursor: pointer;
}

.side-link:hover {
  color: var(--color-primary);
}
</style>
