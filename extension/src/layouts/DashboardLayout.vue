<script setup lang="ts">
// Dashboard 全局布局（设计权威：前端布局 V1.0 §6/§7，样式规范 §6-§12）。
// 结构：Header(64px 深蓝) + Sidebar(220px 深色) + <router-view> 主内容。
// 职责：页面骨架 + 导航状态；Agent 状态/自动模式等由 store 驱动（I3 起接线）。
import { RouterLink, RouterView, useRouter } from "vue-router"
import { onMounted, onUnmounted, ref } from "vue"
import {
  Bot,
  Bell,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  MoreHorizontal,
  Briefcase,
  ScrollText,
  Settings,
  UserCheck,
  X,
} from "lucide-vue-next"
import StatusBadge from "../components/common/StatusBadge.vue"
import ConnectIndicator from "../components/common/ConnectIndicator.vue"
import TodayStats from "../dashboard/TodayStats.vue"
import { useConnectionStore } from "../stores/connection"
import { useEventStore } from "../stores/events"

const connection = useConnectionStore()
const events = useEventStore()

onMounted(() => {
  // 布局级探活：保证任意子页打开时侧栏连接状态正确（文档 §16）
  void connection.checkHealth()
  // 布局级 WS：全局单一事件连接，Overview 实时事件 / 日志页共享（I10）
  events.connect()
})

onUnmounted(() => {
  events.disconnect()
})

const NAV_ITEMS = [
  { path: "/overview", label: "总览", icon: LayoutDashboard },
  { path: "/conversations", label: "聊天会话", icon: MessageSquare },
  { path: "/jobs", label: "岗位管理", icon: Briefcase },
  { path: "/tasks", label: "任务中心", icon: ListChecks },
  { path: "/approvals", label: "人工确认", icon: UserCheck },
  { path: "/logs", label: "日志与事件", icon: ScrollText },
  { path: "/settings", label: "设置", icon: Settings },
]

// 自动模式开关（样式规范 §7）：本地状态，I5 起落 settings store
const autoMode = ref(false)

const router = useRouter()

/** options 页以独立标签打开，「关闭」即关闭当前标签 */
function closeWindow(): void {
  window.close()
}
</script>

<template>
  <div class="dashboard">
    <!-- 顶部 Header（样式规范 §6：62-64px，深蓝 #071426） -->
    <header class="app-header">
      <div class="brand">
        <Bot class="brand-logo" :size="28" aria-hidden="true" />
        <span class="brand-name">AI 求职 Agent</span>
        <span class="brand-version">v1.0.0</span>
      </div>
      <div class="header-actions">
        <StatusBadge status="idle" />
        <button type="button" class="auto-mode" role="switch" :aria-checked="autoMode" @click="autoMode = !autoMode">
          <span class="auto-label">自动模式</span>
          <span class="switch" :class="{ on: autoMode }"><span class="knob" /></span>
        </button>
        <button type="button" class="icon-btn" aria-label="通知"><Bell :size="18" /></button>
        <button type="button" class="icon-btn" aria-label="设置" @click="router.push('/settings')"><Settings :size="18" /></button>
        <button type="button" class="icon-btn" aria-label="更多"><MoreHorizontal :size="18" /></button>
        <button type="button" class="icon-btn" aria-label="关闭" @click="closeWindow"><X :size="18" /></button>
      </div>
    </header>

    <div class="app-body">
      <!-- 左侧导航（V1.0 §6.1：220px，深色 #0B172A） -->
      <aside class="sidebar">
        <nav class="nav" aria-label="主导航">
          <RouterLink v-for="item in NAV_ITEMS" :key="item.path" :to="item.path" class="nav-item">
            <component :is="item.icon" class="nav-icon" :size="19" aria-hidden="true" />
            <span class="nav-label">{{ item.label }}</span>
          </RouterLink>
        </nav>
        <div class="sidebar-bottom">
          <TodayStats />
          <div class="connection">
            <ConnectIndicator :state="connection.state" />
            <span class="connection-url">ws://{{ connection.backendUrl }}</span>
          </div>
        </div>
      </aside>

      <!-- 主内容区（样式规范 §13：Grid 布局，页面自身定义栅格） -->
      <main class="main-content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

/* ===== Header（样式规范 §6：62-64px 深蓝） ===== */
.app-header {
  flex-shrink: 0;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-5);
  background: var(--color-nav-header);
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
  font-size: 18px;
  font-weight: 600;
  color: #ffffff;
}

.brand-version {
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--color-primary);
  color: #ffffff;
  font-size: 11px;
  font-weight: 500;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

/* 自动模式开关（样式规范 §7：44×24，开启品牌蓝） */
.auto-mode {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--color-nav-text);
}

.auto-label {
  font-size: var(--fs-aux);
}

.switch {
  position: relative;
  width: 44px;
  height: 24px;
  border-radius: var(--radius-pill);
  background: #4b5563;
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

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-nav-text);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.icon-btn:hover {
  background: var(--color-nav-hover);
  color: #ffffff;
}

/* ===== Body：Sidebar + Main ===== */
.app-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.sidebar {
  flex-shrink: 0;
  width: 220px;
  display: flex;
  flex-direction: column;
  background: var(--color-nav-bg);
  padding: var(--space-3);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 导航项（V1.0 §6.2：42-46px；样式规范 §9：48px） */
.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: 44px;
  padding: 0 var(--space-4);
  border-radius: var(--radius-md);
  text-decoration: none;
  color: var(--color-nav-text);
  transition: background var(--transition-fast), color var(--transition-fast);
}

.nav-icon {
  color: var(--color-nav-text-muted);
  transition: color var(--transition-fast);
}

.nav-item:hover {
  background: var(--color-nav-hover);
  color: #ffffff;
}

.nav-item:hover .nav-icon {
  color: #ffffff;
}

.nav-item.router-link-active {
  background: var(--color-nav-active);
  color: #ffffff;
}

.nav-item.router-link-active .nav-icon {
  color: #ffffff;
}

.nav-label {
  font-size: var(--fs-body);
}

.sidebar-bottom {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.connection {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--space-1);
}

.connection-url {
  font-size: 11px;
  color: #64748b;
}

/* ===== 主内容（样式规范 §13：padding 18px） ===== */
.main-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 18px;
  background: var(--color-bg-page);
}
</style>
