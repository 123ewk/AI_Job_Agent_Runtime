<script setup lang="ts">
// 岗位详情面板（设计权威：前端布局 V1.0 §19.2，样式规范）。
// 职责：展示选中岗位完整信息 + 匹配评分明细（面板内嵌，Agent 评分后有值，否则 gap-note）+ 删除操作。
// 删除走 job store 乐观移除 + ui toast；删除后父级经 watch 自动重新选中（本组件不关心选择逻辑）。
import { computed, ref } from "vue"
import EmptyState from "../common/EmptyState.vue"
import { jobStatusMeta } from "../../lib/statusMeta"
import { formatRelativeTime } from "../../lib/time"
import type { JobItem } from "../../stores/job"
import { useJobStore } from "../../stores/job"
import { useUiStore } from "../../stores/ui"

const props = defineProps<{
  job: JobItem | null
}>()

const store = useJobStore()
const ui = useUiStore()

const title = computed(() => props.job?.title ?? props.job?.company ?? "未命名岗位")
const status = computed(() => (props.job ? jobStatusMeta(props.job.status) : null))
// 公司已作标题时不再重复展示；其余字段按「标签: 值」网格渲染，空值跳过
const metaRows = computed(() => {
  if (!props.job) return []
  const rows = [
    { label: "公司", value: props.job.company },
    { label: "薪资", value: props.job.salary },
    { label: "地点", value: props.job.location },
    { label: "平台", value: props.job.platform },
  ]
  return rows.filter((r) => Boolean(r.value)) as { label: string; value: string }[]
})

const descExpanded = ref(false)
const acting = ref(false)

async function handleDelete(): Promise<void> {
  const job = props.job
  if (!job || acting.value) return
  if (!window.confirm("确定删除该岗位？此操作不可恢复")) return
  acting.value = true
  try {
    await store.remove(job)
    ui.pushToast("success", "岗位已删除")
  } catch (e) {
    ui.pushToast("error", `删除失败：${e instanceof Error ? e.message : "未知错误"}`)
  } finally {
    acting.value = false
  }
}
</script>

<template>
  <EmptyState v-if="!job" title="未选择岗位" hint="从左侧选择一个岗位查看详情" />

  <div v-else class="job-detail">
    <header class="detail-head">
      <h3 class="detail-title" :title="title">{{ title }}</h3>
      <span v-if="status" class="badge" :style="{ color: status.color, borderColor: status.color }">{{
        status.label
      }}</span>
    </header>

    <dl v-if="metaRows.length" class="meta-grid">
      <template v-for="r in metaRows" :key="r.label">
        <dt>{{ r.label }}</dt>
        <dd :title="r.value">{{ r.value }}</dd>
      </template>
    </dl>

    <!-- 匹配评分：单值 + 明细（§19.2 面板内嵌；关键词权重两成，Agent 评分后才有明细） -->
    <section class="score-section">
      <h4 class="section-title">匹配评分</h4>
      <p v-if="job.score != null" class="score-main">⚡ {{ job.score }}</p>
      <template v-if="job.scoreDetail">
        <div class="score-detail">
          <div class="detail-row">岗位匹配（LLM）：{{ job.scoreDetail.llm_score ?? "—" }}</div>
          <div class="detail-row">关键词匹配（两成）：{{ job.scoreDetail.keyword_score ?? "—" }}</div>
          <div class="detail-row">
            主要匹配：{{ (job.scoreDetail.keyword_hits ?? []).join("、") || "—" }}
          </div>
          <div class="detail-row">
            主要差距：{{ (job.scoreDetail.deductions ?? []).join("；") || "—" }}
          </div>
          <p v-if="job.scoreDetail.llm_reason" class="reason">{{ job.scoreDetail.llm_reason }}</p>
        </div>
      </template>
      <p v-else class="gap-note">评分明细需 Agent 分析完成后出现（Phase 2 补齐）</p>
    </section>

    <section v-if="job.description" class="desc-section">
      <h4 class="section-title">职位描述</h4>
      <p class="desc" :class="{ clamped: !descExpanded }">{{ job.description }}</p>
      <button type="button" class="toggle-btn" @click="descExpanded = !descExpanded">
        {{ descExpanded ? "收起" : "展开" }}
      </button>
    </section>

    <footer class="detail-foot">
      <a
        v-if="job.sourceUrl"
        :href="job.sourceUrl"
        target="_blank"
        rel="noopener noreferrer"
        class="link"
      >
        查看来源
      </a>
      <span class="times">更新于 {{ formatRelativeTime(job.updatedAt) }}</span>
    </footer>

    <div class="actions">
      <button type="button" class="btn danger" :disabled="acting" @click="handleDelete">删除岗位</button>
    </div>
  </div>
</template>

<style scoped>
.job-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-2);
}

.detail-title {
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
  overflow-wrap: break-word;
}

.badge {
  flex-shrink: 0;
  padding: 0 8px;
  border: 1px solid;
  border-radius: var(--radius-pill);
  font-size: var(--fs-badge);
  line-height: 20px;
}

/* 字段网格：标签 80px + 值自适应 */
.meta-grid {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: var(--space-1) var(--space-3);
  margin: 0;
}

.meta-grid dt {
  color: var(--color-text-tertiary);
  font-size: var(--fs-aux);
  line-height: 1.6;
}

.meta-grid dd {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--fs-secondary);
  line-height: 1.6;
  overflow-wrap: break-word;
}

.section-title {
  margin: 0 0 var(--space-2);
  font-size: var(--fs-secondary);
  font-weight: 600;
  color: var(--color-text-secondary);
}

.score-main {
  margin: 0 0 var(--space-2);
  font-size: var(--fs-number);
  font-weight: 600;
  color: var(--color-primary);
}

.score-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-bg-secondary);
  font-size: var(--fs-secondary);
  color: var(--color-text-secondary);
}

.detail-row {
  line-height: 1.6;
}

.reason {
  margin: var(--space-1) 0 0;
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border);
  line-height: 1.6;
  color: var(--color-text-secondary);
}

.gap-note {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-info) 8%, transparent);
  color: var(--color-info);
  font-size: var(--fs-aux);
  line-height: 1.5;
}

.desc-section {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.desc {
  margin: 0;
  font-size: var(--fs-secondary);
  line-height: 1.7;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
  overflow-wrap: break-word;
}

.desc.clamped {
  display: -webkit-box;
  -webkit-line-clamp: 6;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.toggle-btn {
  padding: 0;
  border: none;
  background: none;
  color: var(--color-primary);
  font-size: var(--fs-aux);
  cursor: pointer;
}

.detail-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.link {
  color: var(--color-primary);
  font-size: var(--fs-secondary);
  text-decoration: none;
}

.link:hover {
  text-decoration: underline;
}

.times {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.btn {
  padding: 0 var(--space-4);
  height: 32px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn.danger {
  border: 1px solid var(--color-danger);
  background: var(--color-bg-card);
  color: var(--color-danger);
}

.btn.danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-danger) 8%, transparent);
}
</style>
