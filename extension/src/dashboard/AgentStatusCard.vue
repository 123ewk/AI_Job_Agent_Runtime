<script setup lang="ts">
// Agent 状态卡（设计权威：前端布局 V1.0 §9，样式规范 §16-§19）。
// 结构：标题+状态 Badge ｜ 左状态说明 + 中头像光圈 + 右统计 ｜ 底当前任务+进度点。
// 数据：由 agent store 驱动（文档 §51：不自行猜测状态）；当前后端 WS 为 stub，
//       统计为占位零值，backend 接线后由真实数据替换。
import { Bot } from "lucide-vue-next"
import StatusBadge from "../components/common/StatusBadge.vue"
import { useAgentStore } from "../stores/agent"

const agent = useAgentStore()

const STATS = [
  { label: "会话数", value: 0 },
  { label: "已处理消息", value: 0 },
  { label: "成功回复率", value: "--" },
] as const

// 当前状态描述：监听中显示「监听模式」，否则回退运行态文案
const statusText = () => {
  if (agent.monitoring === "monitoring") return "监听模式"
  if (agent.monitoring === "paused") return "已暂停"
  if (agent.monitoring === "stopped") return "已停止"
  return "空闲"
}

const statusDesc = () => {
  if (agent.monitoring === "monitoring") return "正在监听HR消息..."
  if (agent.currentTask) return agent.currentTask
  return "Agent 待机中，等待任务"
}
</script>

<template>
  <section class="agent-card card">
    <header class="card-head">
      <h3 class="card-title">Agent 状态</h3>
      <StatusBadge :status="agent.uiStatus" />
    </header>

    <div class="agent-body">
      <div class="agent-left">
        <p class="current-label">当前状态</p>
        <p class="current-state">{{ statusText() }}</p>
        <p class="current-desc">{{ statusDesc() }}</p>
      </div>

      <div class="agent-avatar" aria-hidden="true">
        <Bot :size="44" />
      </div>

      <ul class="agent-stats">
        <li v-for="s in STATS" :key="s.label" class="stat">
          <span class="stat-num">{{ s.value }}</span>
          <span class="stat-label">{{ s.label }}</span>
        </li>
      </ul>
    </div>

    <footer class="agent-foot">
      <div class="task">
        <span class="task-label">当前任务</span>
        <span class="task-value">{{ agent.currentTask ?? "无" }}</span>
      </div>
      <div class="progress-dots" :class="{ active: agent.monitoring === 'monitoring' }" aria-hidden="true">
        <span v-for="i in 5" :key="i" class="dot" />
      </div>
    </footer>
  </section>
</template>

<style scoped>
.card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: var(--space-5);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.agent-body {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: var(--space-5);
  margin-top: var(--space-5);
}

.current-label {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.current-state {
  margin: var(--space-1) 0 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.current-desc {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

/* 头像 + 状态光圈（样式规范 §17：96px + 双层淡蓝光晕） */
.agent-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 96px;
  height: 96px;
  border-radius: 50%;
  background: var(--color-bg-secondary);
  color: var(--color-primary);
  box-shadow:
    0 0 0 12px rgba(22, 119, 255, 0.05),
    0 0 0 24px rgba(22, 119, 255, 0.025);
}

.agent-stats {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
}

.stat-num {
  font-size: var(--fs-number);
  font-weight: 600;
  color: var(--color-text-primary);
}

.stat-label {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.agent-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.task-label {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
  margin-right: var(--space-2);
}

.task-value {
  font-size: var(--fs-body);
  font-weight: 500;
  color: var(--color-text-primary);
}

/* 工作状态点（§9：●●●●● 表示 Agent 正在工作） */
.progress-dots {
  display: flex;
  gap: 4px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-border);
  transition: background var(--transition-normal);
}

.progress-dots.active .dot:nth-child(1) {
  animation: dot-active 1.2s ease-in-out infinite;
}
.progress-dots.active .dot:nth-child(2) {
  animation: dot-active 1.2s ease-in-out 0.15s infinite;
}
.progress-dots.active .dot:nth-child(3) {
  animation: dot-active 1.2s ease-in-out 0.3s infinite;
}
.progress-dots.active .dot:nth-child(4) {
  animation: dot-active 1.2s ease-in-out 0.45s infinite;
}
.progress-dots.active .dot:nth-child(5) {
  animation: dot-active 1.2s ease-in-out 0.6s infinite;
}

@keyframes dot-active {
  0%,
  100% {
    background: var(--color-border);
  }
  50% {
    background: var(--color-primary);
  }
}
</style>
