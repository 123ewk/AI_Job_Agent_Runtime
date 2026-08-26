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
import { getActiveSettings, saveActiveSettings } from "../lib/storage"

/** 掩码 api_key（本地明文 key 只在本地 + 推送注册表使用，UI 态用掩码表现）。 */
function maskKey(key: string): string | null {
  if (!key) return null
  if (key.length <= 8) return "****"
  return `${key.slice(0, 4)}...${key.slice(-4)}`
}

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

/**
 * 方案 A 本地真源（chrome.storage.local 的 active_settings 值）。
 * llm.api_key 为**明文**（个人单机扩展私有，明文存储已拍板）；
 * 仅用于设置页还原 + 推送后端进程内注册表，绝不上送后端 GET/PUT 响应。
 */
export interface ActiveSettings {
  llm: {
    provider: string
    base_url: string | null
    model: string
    api_key: string
    temperature: number
  } | null
  job_rule: JobRuleConfig | null
  reply_style: ReplyStyleConfig | null
}

export const useSettingsStore = defineStore("settings", () => {
  const llm = ref<LlmConfig | null>(null)
  const agent = ref<AgentConfig | null>(null)
  const jobRule = ref<JobRuleConfig | null>(null)
  const replyStyle = ref<ReplyStyleConfig | null>(null)
  // 方案 A：明文 api_key 仅存本地真源（后端只回掩码，故需本地还原）。
  // 绝不把 llmKeyPlain 放进任何向后端上送的 GET/PUT 响应体。
  const llmKeyPlain = ref<string>("")
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** 把当前运行时配置（含明文 key）落本地真源（方案 A source of truth）。 */
  function persistActive(): ActiveSettings {
    const active: ActiveSettings = {
      llm: llm.value
        ? {
            provider: llm.value.provider,
            base_url: llm.value.base_url,
            model: llm.value.model,
            api_key: llmKeyPlain.value,
            temperature: llm.value.temperature,
          }
        : null,
      job_rule: jobRule.value,
      reply_style: replyStyle.value,
    }
    void saveActiveSettings(active)
    return active
  }

  /**
   * 推送活动配置到后端进程内注册表（POST /settings/active，本机限定）。
   * 注册表是后端 Agent 运行时读配置的真源（方案 A），进程重启后清空，
   * 靠这里在保存/建连时重推补上。
   */
  async function pushActive(): Promise<void> {
    const active = persistActive()
    if (!active.llm) return
    try {
      await apiPost<{ status: string }>("/settings/active", active)
    } catch (e) {
      // 推送属尽力而为：后端未启动/旧版本无该端点时静默降级，不阻塞 UI
      console.warn("[settings] active config push failed:", e)
    }
  }

  /**
   * 加载设置。方案 A 优先读本地真源（含明文 key，开页「上次一模一样」）；
   * 本地缺（首启/迁移）→ 回退后端 4 分组并落本地 seed。任一失败整体标记 error。
   */
  async function loadAll(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      // 后端先拉（agent 分组本地不存；llm 掩码用于 UI 掩码态与 provider 选项）
      const [l, a, j, r] = await Promise.all([
        apiGet<LlmConfig>("/settings/llm"),
        apiGet<AgentConfig>("/settings/agent"),
        apiGet<JobRuleConfig>("/settings/job-rule"),
        apiGet<ReplyStyleConfig>("/settings/reply-style"),
      ])
      // 本地真源覆盖：还原明文 key/上次值时优先
      const local = await getActiveSettings()
      if (local?.llm) {
        llmKeyPlain.value = local.llm.api_key
        llm.value = {
          provider: local.llm.provider,
          base_url: local.llm.base_url,
          model: local.llm.model,
          api_key_masked: l?.api_key_masked ?? null,
          temperature: local.llm.temperature,
        }
        if (local.job_rule) jobRule.value = local.job_rule
        if (local.reply_style) replyStyle.value = local.reply_style
      } else {
        llm.value = l
        jobRule.value = j
        replyStyle.value = r
        llmKeyPlain.value = ""
      }
      agent.value = a
      // 首启/后端有本地无 → 落盘 seed 一份，便于后续 pushActive
      persistActive()
      // 建连语义：开页后主动推一次注册表，补上进程重启后空注册表
      await pushActive()
    } catch (e) {
      error.value = e instanceof Error ? e.message : "设置加载失败"
    } finally {
      loading.value = false
    }
  }

  /**
   * 保存单个分组。写本地真源（llm 带明文 key）+ 推送注册表。
   * llm 提交后 key 已消耗（密钥替换为掩码态），不再 PUT 回后端（方案 A：DB 不再是真源）。
   */
  async function saveGroup<C>(group: SettingsGroup, patch: C): Promise<void> {
    if (group === "llm") {
      const p = patch as { provider: string; base_url: string | null; model: string; api_key: string; temperature: number }
      // 明文 key 先存本地真源（供还原 + 推送）；UI 态用掩码吸附，不回显明文
      llmKeyPlain.value = p.api_key
      llm.value = {
        provider: p.provider,
        base_url: p.base_url,
        model: p.model,
        api_key_masked: maskKey(p.api_key),
        temperature: p.temperature,
      }
      persistActive()
      await pushActive()
      return
    }
    const updated = await apiPut<C>(`/settings/${group}`, patch)
    applyGroup(group, updated)
    persistActive()
    await pushActive()
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

  return {
    llm,
    agent,
    jobRule,
    replyStyle,
    llmKeyPlain,
    loading,
    error,
    loadAll,
    saveGroup,
    validateLlm,
    pushActive,
  }
})
