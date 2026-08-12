<script setup lang="ts">
// SidePanel 单列面板（设计权威：前端布局 V1.0 §35，样式规范 §47 窄屏模式）。
// 结构：Header(品牌+状态+停止/设置) → 当前任务 → 人工确认(固定) → 最近消息 → Timeline。
// 不显示完整 Sidebar（§35）；数据由 agent/connection store 驱动，真实接线待 backend WS。
import { Bot, Settings, Square } from "lucide-vue-next"
import StatusBadge from "../components/common/StatusBadge.vue"
import EmptyState from "../components/common/EmptyState.vue"
import { useAgentStore } from "../stores/agent"
import { useUiStore } from "../stores/ui"

const agent = useAgentStore()
const ui = useUiStore()

function openSettings(): void {
  void chrome.runtime.openOptionsPage()
}

function stopTask(): void {
  ui.pushToast("info", "停止任务功能待接线")
}
</script>

<template>
  <div class="sidepanel">
    <!-- 顶部：品牌 + Agent 状态 + 操作（§35） -->
    <header class="panel-header">
      <div class="brand">
        <Bot :size="20" class="brand-logo" aria-hidden="true" />
        <span class="brand-name">AI求职Agent</span>
        <StatusBadge :status="agent.uiStatus" />
      </div>
      <div class="header-actions">
        <button type="button" class="icon-btn" aria-label="停止" @click="stopTask"><Square :size="15" /></button>
        <button type="button" class="icon-btn" aria-label="设置" @click="openSettings"><Settings :size="15" /></button>
      </div>
    </header>

    <div class="content">
      <!-- 当前任务（§35） -->
      <section class="card current-task">
        <h3 class="card-title">当前任务</h3>
        <p class="task-name">{{ agent.currentTask ?? "Agent 待机中" }}</p>
        <p class="task-sub">Boss直聘</p>
        <p class="task-runtime">
          <span class="runtime-label">运行时间</span>
          <span class="runtime-value">{{ agent.monitoring === "monitoring" ? "02:34" : "—" }}</span>
        </p>
      </section>

      <!-- 人工确认（高风险问题固定显眼区，§35） -->
      <section class="card approval">
        <h3 class="card-title">
          需要确认
          <span v-if="agent.pendingApprovals.length" class="count-badge">{{ agent.pendingApprovals.length }}</span>
        </h3>
        <EmptyState
          v-if="!agent.pendingApprovals.length"
          title="暂无待确认事项"
          hint="涉及薪资/地点等高风险的决策会固定显示在此"
        />
        <ul v-else class="approval-list">
          <li v-for="a in agent.pendingApprovals" :key="a.approvalId" class="approval-item">
            <p class="approval-type">{{ a.type }}</p>
            <p class="approval-content">{{ a.content }}</p>
            <div class="approval-actions">
              <button type="button" class="btn danger" @click="agent.resolveApproval(a.approvalId)">拒绝</button>
              <button type="button" class="btn primary" @click="agent.resolveApproval(a.approvalId)">通过</button>
            </div>
          </li>
        </ul>
      </section>

      <!-- 最近消息（§35） -->
      <section class="card recent">
        <h3 class="card-title">最近消息</h3>
        <EmptyState title="暂无新消息" hint="收到 HR 消息后显示在这里" />
      </section>

      <!-- Timeline（§35） -->
      <section class="card timeline">
        <h3 class="card-title">执行时间线</h3>
        <EmptyState title="暂无执行记录" hint="Agent 操作步骤将按时间顺序展示" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.sidepanel {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--color-bg-page);
}

/* Header（§35：品牌 + 状态 + 停止/设置） */
.panel-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border);
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

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.icon-btn:hover {
  background: var(--color-bg-secondary);
  color: var(--color-primary);
}

.content {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
}

.card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: var(--space-4);
}

.card-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-3);
  font-size: var(--fs-secondary);
  font-weight: 600;
  color: var(--color-text-primary);
}

/* 当前任务 */
.task-name {
  margin: 0;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--color-text-primary);
}

.task-sub {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.task-runtime {
  display: flex;
  justify-content: space-between;
  margin: var(--space-3) 0 0;
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.runtime-label {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.runtime-value {
  font-size: var(--fs-aux);
  font-weight: 500;
  color: var(--color-text-primary);
}

/* 待确认角标 */
.count-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--color-danger);
  color: #fff;
  font-size: var(--fs-badge);
  font-weight: 500;
  line-height: 18px;
  text-align: center;
}

.approval-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.approval-item {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.approval-type {
  margin: 0;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--color-text-primary);
}

.approval-content {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.approval-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.btn {
  padding: 0 var(--space-3);
  height: 30px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-aux);
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

.btn.danger {
  border: 1px solid var(--color-danger);
  background: var(--color-bg-card);
  color: var(--color-danger);
}

.btn.danger:hover {
  background: #fef2f2;
}
</style>
