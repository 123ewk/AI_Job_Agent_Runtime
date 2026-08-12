<script setup lang="ts">
// 人工确认卡片（设计权威：前端布局 V1.0 §21/§21.1，样式规范 §27-§28）。
// 结构：问题类型 + 内容 + 20s 倒计时 + [通过][拒绝][我知道了]。
// 倒计时：基于后端 expires_at 每秒 tick；归零显示「已超时」并禁用决策。
// 决策直接调 approval store（后端 approve/deny/cancel），成功后父级自动移除卡片。
// §37 要求重要操作用 Modal：此处保留行内按钮以匹配 20s 紧迫性（§21.1），Modal 细化留 Phase 2。
import { computed, onMounted, onUnmounted, ref } from "vue"
import { Clock } from "lucide-vue-next"
import { APPROVAL_TYPE_LABELS, type PendingApproval } from "../../stores/approval"
import { useApprovalStore } from "../../stores/approval"

const props = defineProps<{ approval: PendingApproval }>()

const store = useApprovalStore()

/** 距超时剩余秒数（归零后保持 0） */
const remaining = ref(0)
let timer: number | undefined

function tick(): void {
  if (!props.approval.expiresAt) {
    remaining.value = 0
    return
  }
  const diff = Math.floor((new Date(props.approval.expiresAt).getTime() - Date.now()) / 1000)
  remaining.value = Math.max(0, diff)
}

onMounted(() => {
  tick()
  timer = window.setInterval(tick, 1000)
})
onUnmounted(() => {
  if (timer !== undefined) clearInterval(timer)
})

const expired = computed(() => remaining.value <= 0)
const typeLabel = computed(() => APPROVAL_TYPE_LABELS[props.approval.type] ?? props.approval.type)
const deciding = ref(false)

async function decide(action: "approve" | "deny" | "stop"): Promise<void> {
  if (expired.value || deciding.value) return
  deciding.value = true
  try {
    if (action === "approve") await store.approve(props.approval)
    else if (action === "deny") await store.deny(props.approval)
    else await store.stopTask(props.approval)
  } finally {
    deciding.value = false
  }
}
</script>

<template>
  <article class="approval-card" :class="{ expired }">
    <header class="card-head">
      <span class="type-tag">{{ typeLabel }}</span>
      <span class="countdown" :class="{ urgent: !expired && remaining <= 5 }">
        <Clock :size="13" aria-hidden="true" />
        {{ expired ? "已超时" : `${remaining}s` }}
      </span>
    </header>

    <p class="content">{{ approval.content }}</p>

    <footer class="card-actions">
      <template v-if="!expired">
        <button type="button" class="btn" :disabled="deciding" @click="decide('stop')">我知道了</button>
        <button type="button" class="btn danger" :disabled="deciding" @click="decide('deny')">拒绝</button>
        <button type="button" class="btn primary" :disabled="deciding" @click="decide('approve')">通过</button>
      </template>
      <p v-else class="timeout-hint">已超时：Agent 将发送预设的 AI 助手身份说明（§21.1）</p>
    </footer>
  </article>
</template>

<style scoped>
.approval-card {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}

.approval-card.expired {
  opacity: 0.7;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.type-tag {
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  font-size: var(--fs-aux);
  font-weight: 500;
  color: var(--color-text-secondary);
}

/* 倒计时（§21.1：明显但不刺眼；≤5s 转危险色） */
.countdown {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-secondary);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--color-warning);
}

.countdown.urgent {
  color: var(--color-danger);
}

.content {
  margin: var(--space-3) 0 0;
  font-size: var(--fs-body);
  line-height: 1.6;
  color: var(--color-text-primary);
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-3);
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

.btn.primary {
  border: none;
  background: var(--color-primary);
  color: #fff;
}

.btn.primary:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.btn.danger {
  border: 1px solid var(--color-danger);
  background: var(--color-bg-card);
  color: var(--color-danger);
}

.btn.danger:hover:not(:disabled) {
  background: #fef2f2;
}

.btn:not(.primary):not(.danger) {
  border: 1px solid var(--color-border-strong);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
}

.btn:not(.primary):not(.danger):hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.timeout-hint {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}
</style>
