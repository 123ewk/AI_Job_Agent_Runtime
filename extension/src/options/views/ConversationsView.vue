<script setup lang="ts">
// 聊天会话页（设计权威：前端布局 V1.0 §17-§18，样式规范 §38）。
// 结构：三栏 = 会话列表（左）+ 聊天窗口（中）+ Agent 信息（右）。
// 数据：conversation store 对接后端 /conversations（列表/消息/发送）。
// 已知缺口（诚实标注）：会话列表无 last_message 预览、右侧匹配评分/任务状态后端无字段 → 空态标注（Phase 2 补齐）。
import { nextTick, onMounted, ref, watch } from "vue"
import EmptyState from "../../components/common/EmptyState.vue"
import ErrorState from "../../components/common/ErrorState.vue"
import ConversationCard from "../../components/domain/ConversationCard.vue"
import MessageBubble from "../../components/domain/MessageBubble.vue"
import { conversationStatusMeta } from "../../lib/statusMeta"
import { formatRelativeTime } from "../../lib/time"
import { useConversationStore } from "../../stores/conversation"

const store = useConversationStore()
const draft = ref("")
const msgScroll = ref<HTMLElement | null>(null)

onMounted(() => {
  void store.fetchConversations()
})

/** 消息发送失败时的重试入口（仅对已选中会话有效） */
function retryMessages(): void {
  if (store.currentId !== null) void store.select(store.currentId)
}

/** 回车发送（Shift+Enter 换行）；composition 期间不触发，避免中文输入法确认上屏误发送 */
function onKeydown(e: KeyboardEvent): void {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    void handleSend()
  }
}

async function handleSend(): Promise<void> {
  const text = draft.value.trim()
  if (!text || store.sending) return
  const ok = await store.send(text)
  if (ok) draft.value = ""
}

/** 消息数变化（新消息/切换会话）后滚动到底部 */
watch(
  () => store.messages.length,
  async () => {
    await nextTick()
    if (msgScroll.value) msgScroll.value.scrollTop = msgScroll.value.scrollHeight
  },
)
</script>

<template>
  <div class="conversations-page">
    <!-- 左：会话列表（§17.1） -->
    <aside class="col-list">
      <header class="list-head">
        <h2 class="page-title">聊天会话</h2>
        <button type="button" class="refresh-btn" @click="store.fetchConversations()">刷新</button>
      </header>

      <ErrorState
        v-if="store.error && !store.conversations.length"
        :message="`拉取会话失败：${store.error}`"
        @retry="store.fetchConversations()"
      />
      <EmptyState
        v-else-if="!store.loading && !store.conversations.length"
        title="暂无会话"
        hint="进入 Boss 聊天并触发同步后，会话会出现在这里"
      />
      <div v-else class="list-scroll">
        <ConversationCard
          v-for="c in store.conversations"
          :key="c.id"
          :conversation="c"
          :active="c.id === store.currentId"
          @click="store.select(c.id)"
        />
      </div>
    </aside>

    <!-- 中：聊天窗口（§17.2） -->
    <section class="col-chat">
      <template v-if="store.current">
        <header class="chat-head">
          <strong class="chat-title">{{ store.current.hrName ?? store.current.jobTitle ?? "会话" }}</strong>
          <span class="chat-status" :style="{ color: conversationStatusMeta(store.current.status).color }">
            {{ conversationStatusMeta(store.current.status).label }}
          </span>
        </header>

        <div ref="msgScroll" class="chat-scroll">
          <ErrorState v-if="store.messagesError" :message="`消息加载失败：${store.messagesError}`" @retry="retryMessages" />
          <EmptyState
            v-else-if="!store.messagesLoading && !store.messages.length"
            title="暂无消息"
            hint="发送第一条消息，或从 Boss 页面同步聊天记录"
          />
          <div v-else class="msg-list">
            <MessageBubble v-for="m in store.messages" :key="m.id" :message="m" />
          </div>
        </div>

        <footer class="chat-input">
          <textarea
            v-model="draft"
            class="input"
            rows="2"
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            @keydown="onKeydown"
          />
          <button
            type="button"
            class="send-btn"
            :disabled="store.sending || !draft.trim()"
            @click="handleSend"
          >
            {{ store.sending ? "发送中…" : "发送" }}
          </button>
        </footer>
      </template>

      <EmptyState v-else title="选择一个会话" hint="从左侧列表选择会话查看消息" />
    </section>

    <!-- 右：Agent 信息（§18 聊天详情） -->
    <aside class="col-info">
      <template v-if="store.current">
        <h3 class="info-title">会话信息</h3>
        <dl class="info-list">
          <dt>职位</dt>
          <dd>{{ store.current.jobTitle ?? "—" }}</dd>
          <dt>HR</dt>
          <dd>{{ store.current.hrName ?? "—" }}</dd>
          <dt>状态</dt>
          <dd>{{ conversationStatusMeta(store.current.status).label }}</dd>
          <dt>最后同步</dt>
          <dd>{{ formatRelativeTime(store.current.lastSyncedAt) }}</dd>
        </dl>
        <p class="gap-note">匹配评分、任务状态等字段后端暂未提供，将在 Phase 2 补齐</p>
      </template>
      <EmptyState v-else title="未选择会话" hint="选择会话后查看详情" />
    </aside>
  </div>
</template>

<style scoped>
/* 三栏 Grid：100vh - Header64 - main-content padding 18*2 */
.conversations-page {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 240px;
  gap: var(--space-4);
  height: calc(100vh - 100px);
  min-height: 0;
}

/* 通用栏容器：flex 纵向 + 内部滚动，栏自身不溢出 */
.col-list,
.col-chat,
.col-info {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

/* ===== 左：会话列表 ===== */
.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.page-title {
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.refresh-btn {
  padding: 0 var(--space-3);
  height: 28px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  font-size: var(--fs-secondary);
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast);
}

.refresh-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.list-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
}

/* ===== 中：聊天窗口 ===== */
.chat-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.chat-title {
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.chat-status {
  font-size: var(--fs-aux);
  font-weight: 500;
}

.chat-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.msg-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.chat-input {
  display: flex;
  gap: var(--space-3);
  flex-shrink: 0;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--color-border);
}

.input {
  flex: 1;
  resize: none;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-bg-page);
  color: var(--color-text-primary);
  font-family: inherit;
  font-size: var(--fs-body);
  line-height: 1.5;
}

.input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.send-btn {
  align-self: flex-end;
  height: 32px;
  padding: 0 var(--space-4);
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: #ffffff;
  font-size: var(--fs-secondary);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.send-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.send-btn:disabled {
  background: var(--color-text-disabled);
  cursor: not-allowed;
}

/* ===== 右：Agent 信息（§18） ===== */
.col-info {
  padding: var(--space-4);
  gap: var(--space-4);
}

.info-title {
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.info-list {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.info-list dt {
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.info-list dd {
  margin: 0;
  font-size: var(--fs-body);
  color: var(--color-text-primary);
}

.gap-note {
  margin: 0;
  padding: var(--space-3);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-sm);
  font-size: var(--fs-aux);
  line-height: 1.5;
  color: var(--color-text-tertiary);
}
</style>
