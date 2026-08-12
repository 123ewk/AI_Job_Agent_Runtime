<script setup lang="ts">
// 人工确认（设计权威：前端布局 V1.0 §13，样式规范 §27-§28）。
// 标题「人工确认 (N)」+ 高风险事项卡片（拒绝/通过）。红点角标由数量表达。
// 数据：agent store pendingApprovals（WS 消息驱动）；真实 Approval 落库/接口在增量 I6。
import { useAgentStore } from "../stores/agent"
import EmptyState from "../components/common/EmptyState.vue"

const agent = useAgentStore()

// 占位决策：本地移除待确认项；真实提交走 /tasks/{id}/approvals（增量 I6）
function decide(approvalId: string): void {
  agent.resolveApproval(approvalId)
}
</script>

<template>
  <section class="approvals card">
    <header class="card-head">
      <h3 class="card-title">
        人工确认
        <span v-if="agent.pendingApprovals.length" class="count-badge">{{ agent.pendingApprovals.length }}</span>
      </h3>
      <button type="button" class="link-btn">全部 &gt;</button>
    </header>

    <EmptyState
      v-if="!agent.pendingApprovals.length"
      title="暂无待确认事项"
      hint="涉及薪资/地点/加班等高风险决策时会出现在这里"
    />
    <ul v-else class="approval-list">
      <li v-for="a in agent.pendingApprovals" :key="a.approvalId" class="approval-item">
        <p class="approval-type">{{ a.type }}</p>
        <p class="approval-content">{{ a.content }}</p>
        <div class="approval-actions">
          <button type="button" class="btn danger" @click="decide(a.approvalId)">拒绝</button>
          <button type="button" class="btn primary" @click="decide(a.approvalId)">通过</button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: var(--space-5);
  height: 100%;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

/* 待确认红点角标（样式规范 §10 危险 #EF4444） */
.count-badge {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: var(--color-danger);
  color: #fff;
  font-size: var(--fs-badge);
  font-weight: 500;
  line-height: 20px;
  text-align: center;
}

.link-btn {
  border: none;
  background: transparent;
  font-size: var(--fs-secondary);
  color: var(--color-text-tertiary);
  cursor: pointer;
}

.link-btn:hover {
  color: var(--color-primary);
}

.approval-list {
  list-style: none;
  margin: var(--space-4) 0 0;
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

/* 按钮（样式规范 §37/§28）：通过蓝底优先、拒绝红描边 */
.btn {
  padding: 0 var(--space-4);
  height: 32px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-secondary);
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
