// 用户设置 store（I7 重构为后端驱动，对接 /api/v1/settings/{group}）。
// 职责：拉取/保存 4 个分组配置（llm/agent/job-rule/reply-style）+ LLM 连通性测试。
// 后端契约：
//   - GET  /settings/{group}         → 分组配置（llm 返回 api_key_masked，明文不下发）
//   - PUT  /settings/{group}         → 保存（llm 需 api_key 非空，空串会覆盖真实密钥——见 service 落库逻辑）
//   - POST /settings/validate-llm    → { ok, detail }
// 已知缺口：简历/聊天/后台监听/数据同步/高级设置等分组后端暂无接口 → 菜单不展示（Phase 2 补齐）。
import { defineStore } from "pinia"
import { ref } from "vue"
import { apiGet, apiPost, apiPut } from "../lib/api"

// 保留旧 Phase 1 本地类型：storage.ts / background 仍按 app_settings 读写本地偏好
export type LLMProvider = "doubao" | "openai" | "anthropic" | "qwen" | "deepseek"
export type ReplyStyle = "polite" | "professional" | "concise" | "friendly"

export interface AppSettings {
  llmProvider: LLMProvider
  apiKey: string
  apiBaseUrl?: string
  autoReply: boolean
  autoApply: boolean
  concurrency: number
  replyStyle: ReplyStyle
}

// ---------------- 后端分组配置（schema/setting.py 对齐） ----------------

export interface LlmConfig {
  provider: string
  base_url: string | null
  model: string
  api_key_masked: string | null
  temperature: number
}

export interface AgentConfig {
  concurrency_limit: number
  auto_reply_enabled: boolean
  auto_approval_threshold: number
  approval_timeout_seconds: number
  max_retries: number
}

export interface JobRuleConfig {
  min_salary: number | null
  max_salary: number | null
  preferred_locations: string[] | null
  overtime_allowed: boolean
  outsourcing_allowed: boolean
  offsite_allowed: boolean
}

export interface ReplyStyleConfig {
  tone: string
  formality: string
  length_preference: string
  include_greeting: boolean
  include_closing: boolean
}

/** URL 用的分组名（与后端路由一致：job-rule 带连字符） */
export type SettingsGroup = "llm" | "agent" | "job-rule" | "reply-style"

export const useSettingsStore = defineStore("settings", () => {
  const llm = ref<LlmConfig | null>(null)
  const agent = ref<AgentConfig | null>(null)
  const jobRule = ref<JobRuleConfig | null>(null)
  const replyStyle = ref<ReplyStyleConfig | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  /**
   * 并行拉取 4 个分组。任一失败即整体标记 error（页面显示重试），
   * 不部分覆盖已加载数据，避免脏混合（文档 §51：UI 不猜测后端状态）。
   */
  async function loadAll(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [l, a, j, r] = await Promise.all([
        apiGet<LlmConfig>("/settings/llm"),
        apiGet<AgentConfig>("/settings/agent"),
        apiGet<JobRuleConfig>("/settings/job-rule"),
        apiGet<ReplyStyleConfig>("/settings/reply-style"),
      ])
      llm.value = l
      agent.value = a
      jobRule.value = j
      replyStyle.value = r
    } catch (e) {
      error.value = e instanceof Error ? e.message : "设置加载失败"
    } finally {
      loading.value = false
    }
  }

  /** 保存单个分组（PUT /settings/{group}），成功后用返回的最新值刷新本地 */
  async function saveGroup<C>(group: SettingsGroup, patch: C): Promise<void> {
    const updated = await apiPut<C>(`/settings/${group}`, patch)
    applyGroup(group, updated)
  }

  /** 保存后回写对应分组状态（llm 返回掩码 Key，字段名不一致需特判） */
  function applyGroup<C>(group: SettingsGroup, updated: C): void {
    if (group === "llm") llm.value = updated as LlmConfig
    else if (group === "agent") agent.value = updated as AgentConfig
    else if (group === "job-rule") jobRule.value = updated as JobRuleConfig
    else replyStyle.value = updated as ReplyStyleConfig
  }

  /**
   * LLM 连通性测试（POST /settings/validate-llm）。
   * 传入表单当前填写的值，后端据此探测（未落库也能测）；不传则回退已保存配置。
   */
  async function validateLlm(payload?: {
    provider: string
    base_url: string | null
    model: string
    api_key: string
    temperature: number
  }): Promise<{ ok: boolean; detail: string }> {
    return apiPost<{ ok: boolean; detail: string }>(
      "/settings/validate-llm",
      payload ?? {},
    )
  }

  return { llm, agent, jobRule, replyStyle, loading, error, loadAll, saveGroup, validateLlm }
})
