<script setup lang="ts">
// 今日数据（设计权威：前端布局 V1.0 §15，样式规范 §11）。
// 职责：Sidebar 底部的当日统计卡片（消息处理/发送消息/申请投递/匹配岗位/运行时长）。
// 数据：默认占位零值，I3 起由 agent store / 后端接线驱动。
defineProps<{
  messagesHandled?: number
  messagesSent?: number
  applications?: number
  jobsMatched?: number
  runDuration?: string
}>()
</script>

<template>
  <section class="today-stats" aria-label="今日数据">
    <h3 class="title">今日数据</h3>
    <ul class="stats">
      <li class="stat">
        <span class="num">{{ messagesHandled ?? 0 }}</span>
        <span class="label">消息处理</span>
      </li>
      <li class="stat">
        <span class="num">{{ messagesSent ?? 0 }}</span>
        <span class="label">发送消息</span>
      </li>
      <li class="stat">
        <span class="num">{{ applications ?? 0 }}</span>
        <span class="label">申请投递</span>
      </li>
      <li class="stat">
        <span class="num">{{ jobsMatched ?? 0 }}</span>
        <span class="label">匹配岗位</span>
      </li>
    </ul>
    <div class="runtime">
      <span class="runtime-label">运行时长</span>
      <span class="runtime-value">{{ runDuration ?? "—" }}</span>
    </div>
  </section>
</template>

<style scoped>
.today-stats {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-card);
  background: var(--color-nav-card);
}

.title {
  margin: 0 0 var(--space-3);
  font-size: var(--fs-aux);
  font-weight: 500;
  color: var(--color-nav-text-muted);
}

.stats {
  list-style: none;
  margin: 0;
  padding: 0;
}

.stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: var(--space-2) 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.stat:last-child {
  border-bottom: none;
}

.num {
  font-size: var(--fs-number);
  font-weight: 600;
  color: #ffffff;
  line-height: 1;
}

.label {
  font-size: var(--fs-aux);
  color: #94a3b8;
}

.runtime {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding-top: var(--space-2);
}

.runtime-label {
  font-size: var(--fs-aux);
  color: #94a3b8;
}

.runtime-value {
  font-size: var(--fs-secondary);
  font-weight: 500;
  color: var(--color-nav-text);
}
</style>
