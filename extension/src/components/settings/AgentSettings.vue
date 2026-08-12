<script setup lang="ts">
// Agent 策略面板（设计权威：前端布局 V1.0 §25/§26，后端 /settings/agent）。
// 字段：并发数/自动回复/自动确认阈值/确认超时/最大重试。
import { computed, ref, watch } from "vue"
import { useSettingsStore, type AgentConfig } from "../../stores/settings"
import { useUiStore } from "../../stores/ui"
import SettingsPanel from "./SettingsPanel.vue"
import BaseSwitch from "./BaseSwitch.vue"
import "./SettingsForm.css"

const store = useSettingsStore()
const ui = useUiStore()

interface AgentForm {
  concurrency_limit: number
  auto_reply_enabled: boolean
  auto_approval_threshold: number
  approval_timeout_seconds: number
  max_retries: number
}

function toForm(cfg: AgentConfig | null): AgentForm {
  return {
    concurrency_limit: cfg?.concurrency_limit ?? 3,
    auto_reply_enabled: cfg?.auto_reply_enabled ?? false,
    auto_approval_threshold: cfg?.auto_approval_threshold ?? 0.9,
    approval_timeout_seconds: cfg?.approval_timeout_seconds ?? 20,
    max_retries: cfg?.max_retries ?? 2,
  }
}

const form = ref<AgentForm>(toForm(store.agent))
watch(
  () => store.agent,
  (v) => {
    if (v) form.value = toForm(v)
  },
)

const dirty = computed(
  () =>
    store.agent !== null &&
    (form.value.concurrency_limit !== store.agent!.concurrency_limit ||
      form.value.auto_reply_enabled !== store.agent!.auto_reply_enabled ||
      form.value.auto_approval_threshold !== store.agent!.auto_approval_threshold ||
      form.value.approval_timeout_seconds !== store.agent!.approval_timeout_seconds ||
      form.value.max_retries !== store.agent!.max_retries),
)

const saving = ref(false)

function adjust(key: "concurrency_limit" | "max_retries", delta: number): void {
  const min = key === "max_retries" ? 0 : 1
  const max = key === "max_retries" ? 5 : 10
  const next = form.value[key] + delta
  if (next >= min && next <= max) form.value[key] = next
}

async function handleSave(): Promise<void> {
  saving.value = true
  try {
    await store.saveGroup("agent", { ...form.value })
    ui.pushToast("success", "Agent 策略已保存")
  } catch (e) {
    ui.pushToast("error", `保存失败：${e instanceof Error ? e.message : "未知错误"}`)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <SettingsPanel title="Agent 策略" description="并发、自动回复与人工确认行为" :dirty="dirty" :saving="saving" @save="handleSave">
    <div class="form-field">
      <label class="form-label">同时运行任务数</label>
      <div class="form-stepper">
        <button type="button" @click="adjust('concurrency_limit', -1)">−</button>
        <span class="form-stepper-value">{{ form.concurrency_limit }}</span>
        <button type="button" @click="adjust('concurrency_limit', 1)">+</button>
      </div>
      <p class="form-hint">1-10；建议 1-3，过高可能触发平台风控</p>
    </div>

    <BaseSwitch v-model="form.auto_reply_enabled" label="自动回复" hint="普通消息自动回复，敏感问题需确认" />

    <hr class="form-divider" />

    <div class="form-grid">
      <div class="form-field">
        <label class="form-label" for="agent-threshold">自动确认置信度阈值</label>
        <input
          id="agent-threshold"
          v-model.number="form.auto_approval_threshold"
          class="form-input"
          type="number"
          min="0"
          max="1"
          step="0.05"
        />
        <p class="form-hint">0-1，低于阈值进入人工确认</p>
      </div>
      <div class="form-field">
        <label class="form-label" for="agent-timeout">人工确认超时（秒）</label>
        <input
          id="agent-timeout"
          v-model.number="form.approval_timeout_seconds"
          class="form-input"
          type="number"
          min="10"
          max="120"
          step="5"
        />
        <p class="form-hint">10-120 秒，超时自动降级（默认 20s）</p>
      </div>
    </div>

    <div class="form-field">
      <label class="form-label">任务失败最大重试次数</label>
      <div class="form-stepper">
        <button type="button" @click="adjust('max_retries', -1)">−</button>
        <span class="form-stepper-value">{{ form.max_retries }}</span>
        <button type="button" @click="adjust('max_retries', 1)">+</button>
      </div>
    </div>
  </SettingsPanel>
</template>
