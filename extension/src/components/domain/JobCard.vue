<script setup lang="ts">
// 岗位列表卡片（设计权威：前端布局 V1.0 §19.1，样式规范）。
// 职责：岗位摘要（标题/公司/薪资/地点/状态徽章/评分/相对时间）；纯展示，active 高亮由父级传入。
// 说明：根元素是 <button>，父级 @click 通过属性透传落到按钮上（对齐 ConversationCard）。
import { computed } from "vue"
import { jobStatusMeta } from "../../lib/statusMeta"
import { formatRelativeTime } from "../../lib/time"
import type { JobItem } from "../../stores/job"

const props = defineProps<{
  job: JobItem
  active?: boolean
}>()

const title = computed(() => props.job.title ?? props.job.company ?? "未命名岗位")
const status = computed(() => jobStatusMeta(props.job.status))
// 公司已作标题时不再重复展示；薪资/地点/公司按「·」拼接
const subtitle = computed(() => {
  const parts = [props.job.company, props.job.salary, props.job.location].filter((x): x is string => Boolean(x))
  if (!props.job.title) parts.shift()
  return parts.join(" · ") || "—"
})
</script>

<template>
  <button type="button" class="job-card" :class="{ active }">
    <div class="row">
      <span class="title" :title="title">{{ title }}</span>
      <span class="badge" :style="{ color: status.color, borderColor: status.color }">{{ status.label }}</span>
    </div>
    <div class="row">
      <span class="subtitle" :title="subtitle">{{ subtitle }}</span>
      <span v-if="job.score != null" class="score" :title="`匹配评分 ${job.score}`">⚡{{ job.score }}</span>
    </div>
    <div class="row">
      <span class="time">{{ formatRelativeTime(job.updatedAt) }}</span>
    </div>
  </button>
</template>

<style scoped>
.job-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.job-card:hover {
  border-color: var(--color-primary);
}

.job-card.active {
  border-color: var(--color-primary);
  background: var(--color-bg-secondary);
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-width: 0;
}

.title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--color-text-primary);
}

.subtitle {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-secondary);
  color: var(--color-text-secondary);
}

.time {
  flex-shrink: 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.badge {
  flex-shrink: 0;
  padding: 0 6px;
  border: 1px solid;
  border-radius: var(--radius-pill);
  font-size: var(--fs-badge);
  line-height: 18px;
}

/* 评分 chip：仅已有评分时展示，主色高亮（§19.1 匹配评分） */
.score {
  flex-shrink: 0;
  padding: 0 8px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--color-primary);
  font-size: var(--fs-aux);
  font-weight: 600;
  line-height: 20px;
}
</style>
