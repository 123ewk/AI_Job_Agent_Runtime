<script setup lang="ts">
// 总览（设计权威：前端布局 V1.0 §8-§16，样式规范 §13 主内容 Grid）。
// 布局：左列(Agent状态/最近会话/任务进度) + 右列 388px(实时事件/人工确认/快捷操作)。
// 生命周期：挂载时探活后端 health，驱动连接状态（§16）。
import { onMounted } from "vue"
import { useRouter } from "vue-router"
import { useConnectionStore } from "../../stores/connection"
import AgentStatusCard from "../../dashboard/AgentStatusCard.vue"
import RecentSessions from "../../dashboard/RecentSessions.vue"
import TaskProgress from "../../dashboard/TaskProgress.vue"
import RealtimeEvents from "../../dashboard/RealtimeEvents.vue"
import HumanConfirmations from "../../dashboard/HumanConfirmations.vue"
import QuickActions from "../../dashboard/QuickActions.vue"

const router = useRouter()
const connection = useConnectionStore()

onMounted(() => {
  void connection.checkHealth()
})
</script>

<template>
  <div class="overview">
    <div class="overview-main">
      <AgentStatusCard />
      <RecentSessions @view-all="router.push('/conversations')" />
      <TaskProgress />
    </div>
    <aside class="overview-side">
      <RealtimeEvents />
      <HumanConfirmations />
      <QuickActions />
    </aside>
  </div>
</template>

<style scoped>
.overview {
  display: grid;
  grid-template-columns: minmax(600px, 1fr) 388px;
  gap: var(--space-4);
  align-items: start;
}

.overview-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.overview-side {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* 窄屏降级（样式规范 §46 <1000px：右侧折叠为抽屉，暂以单列兜底） */
@media (max-width: 1000px) {
  .overview {
    grid-template-columns: 1fr;
  }
}
</style>
