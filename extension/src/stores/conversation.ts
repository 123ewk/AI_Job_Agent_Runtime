// 会话 store（设计权威：前端布局 V1.0 §17-§18，样式规范 §38）。
// 职责：拉取会话列表、切换当前会话并拉取消息历史、发送用户消息。
// 后端契约（Phase 2 REST，schema/conversation.py）：
//   - GET  /conversations?page=1&page_size=50      → PaginatedResponse<ConversationResponse>
//   - GET  /conversations/{id}/messages?limit=100  → MessageResponse[]（按发送时间正序）
//   - POST /conversations/{id}/messages            → MessageResponse（body: role/content/source/external_msg_id/sent_at）
// 已知缺口：会话列表接口只回会话元数据，无 last_message 预览字段 → 列表卡片显示 HR/职位/状态/时间，
//   「最新消息预览」标注为 Phase 2 补齐（避免按会话 N+1 拉全量消息）。
import { computed, ref } from "vue"
import { defineStore } from "pinia"
import { apiGet, apiPost } from "../lib/api"

/** 前端消费的会话（由 ConversationResponse 映射） */
export interface Conversation {
  id: number
  /** HR 姓名（可为空，空时卡片降级显示职位名） */
  hrName: string | null
  jobTitle: string | null
  platform: string
  /** 会话状态（后端小写）：active / waiting_hr / closed */
  status: string
  lastSyncedAt: string | null
  updatedAt: string
}

/** 前端消费的消息（由 MessageResponse 映射） */
export interface ChatMessage {
  id: number
  conversationId: number
  /** 消息角色（后端小写）：user / hr / agent / system */
  role: string
  content: string
  /** 来源（后端小写）：manual / agent / history */
  source: string
  sentAt: string | null
}

/** 后端 ConversationResponse（schema/conversation.py：id/uuid/thread_id/status/hr_name/job_title/...） */
interface ConversationResponseDto {
  id: number
  user_id: number
  job_id: number | null
  hr_id: number | null
  uuid: string
  thread_id: string
  status: string
  platform: string
  external_id: string
  hr_name: string | null
  job_title: string | null
  last_synced_at: string | null
  created_at: string
  updated_at: string
}

/** 后端 MessageResponse（schema/conversation.py：id/conversation_id/role/content/source/sent_at/...） */
interface MessageResponseDto {
  id: number
  conversation_id: number
  user_id: number
  role: string
  content: string
  source: string
  external_msg_id: string | null
  sent_at: string | null
  created_at: string
}

function toConversation(dto: ConversationResponseDto): Conversation {
  return {
    id: dto.id,
    hrName: dto.hr_name,
    jobTitle: dto.job_title,
    platform: dto.platform,
    status: dto.status,
    lastSyncedAt: dto.last_synced_at,
    updatedAt: dto.updated_at,
  }
}

function toMessage(dto: MessageResponseDto): ChatMessage {
  return {
    id: dto.id,
    conversationId: dto.conversation_id,
    role: dto.role,
    content: dto.content,
    source: dto.source,
    // 后端 sent_at 可为空；兜底用入库时间，保证气泡至少能显示时间
    sentAt: dto.sent_at ?? dto.created_at,
  }
}

export const useConversationStore = defineStore("conversation", () => {
  const conversations = ref<Conversation[]>([])
  const currentId = ref<number | null>(null)
  const messages = ref<ChatMessage[]>([])
  const loading = ref(false) // 会话列表加载中
  const error = ref<string | null>(null) // 会话列表错误
  const messagesLoading = ref(false) // 当前会话消息加载中
  const messagesError = ref<string | null>(null) // 消息加载/发送错误
  const sending = ref(false) // 发送消息中

  /** 当前选中会话（派生） */
  const current = computed<Conversation | null>(
    () => conversations.value.find((c) => c.id === currentId.value) ?? null,
  )

  /** 拉取会话列表（按 updated_at 倒序）；若当前选中项已不在列表则复位选中态 */
  async function fetchConversations(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await apiGet<{ items: ConversationResponseDto[] }>("/conversations?page=1&page_size=50")
      conversations.value = res.items.map(toConversation)
      if (currentId.value !== null && !conversations.value.some((c) => c.id === currentId.value)) {
        currentId.value = null
        messages.value = []
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : "拉取会话列表失败"
    } finally {
      loading.value = false
    }
  }

  /** 切换当前会话并拉取其消息历史（重复点击已选会话为空操作） */
  async function select(id: number): Promise<void> {
    if (id === currentId.value) return
    currentId.value = id
    messages.value = []
    messagesError.value = null
    messagesLoading.value = true
    try {
      const list = await apiGet<MessageResponseDto[]>(`/conversations/${id}/messages?limit=100`)
      messages.value = list.map(toMessage)
    } catch (e) {
      messagesError.value = e instanceof Error ? e.message : "拉取消息失败"
    } finally {
      messagesLoading.value = false
    }
  }

  /**
   * 发送用户消息（role=user, source=manual）。
   * 返回是否成功：失败时输入框保留内容并展示错误，由调用方决定。
   * 成功后本地追加消息，并近似更新会话时间置顶（不回读后端 updated_at，V1 可接受）。
   */
  async function send(content: string): Promise<boolean> {
    const id = currentId.value
    if (!id || !content.trim()) return false
    sending.value = true
    messagesError.value = null
    try {
      const msg = await apiPost<MessageResponseDto>(`/conversations/${id}/messages`, {
        role: "user",
        content: content.trim(),
        source: "manual",
      })
      messages.value.push(toMessage(msg))
      const idx = conversations.value.findIndex((c) => c.id === id)
      if (idx !== -1) {
        const conv = { ...conversations.value[idx], updatedAt: msg.created_at }
        conversations.value.splice(idx, 1)
        conversations.value.unshift(conv)
      }
      return true
    } catch (e) {
      messagesError.value = e instanceof Error ? e.message : "发送消息失败"
      return false
    } finally {
      sending.value = false
    }
  }

  return {
    conversations,
    currentId,
    current,
    messages,
    loading,
    error,
    messagesLoading,
    messagesError,
    sending,
    fetchConversations,
    select,
    send,
  }
})
