<script setup lang="ts">
// 回复风格面板（设计权威：前端布局 V1.0 §29，后端 /settings/reply-style）。
// 字段：语气/正式程度/长度偏好 + 问候/结束语开关。
import { computed, ref, watch } from "vue"
import { useSettingsStore, type ReplyStyleConfig } from "../../stores/settings"
import { useUiStore } from "../../stores/ui"
import SettingsPanel from "./SettingsPanel.vue"
import BaseSwitch from "./BaseSwitch.vue"
import "./SettingsForm.css"

const store = useSettingsStore()
const ui = useUiStore()

interface ReplyStyleForm {
  tone: string
  formality: string
  length_preference: string
  include_greeting: boolean
  include_closing: boolean
}

function toForm(cfg: ReplyStyleConfig | null): ReplyStyleForm {
  return {
    tone: cfg?.tone ?? "professional",
    formality: cfg?.formality ?? "formal",
    length_preference: cfg?.length_preference ?? "medium",
    include_greeting: cfg?.include_greeting ?? true,
    include_closing: cfg?.include_closing ?? true,
  }
}

const form = ref<ReplyStyleForm>(toForm(store.replyStyle))
watch(
  () => store.replyStyle,
  (v) => {
    if (v) form.value = toForm(v)
  },
)

const dirty = computed(
  () =>
    store.replyStyle !== null &&
    (form.value.tone !== store.replyStyle!.tone ||
      form.value.formality !== store.replyStyle!.formality ||
      form.value.length_preference !== store.replyStyle!.length_preference ||
      form.value.include_greeting !== store.replyStyle!.include_greeting ||
      form.value.include_closing !== store.replyStyle!.include_closing),
)

const saving = ref(false)

const RADIO_GROUPS = [
  {
    key: "tone",
    label: "语气",
    options: [
      { value: "professional", name: "专业", desc: "直击要点，专业表达" },
      { value: "friendly", name: "亲切", desc: "温和语气，拉近距离" },
      { value: "concise", name: "简洁", desc: "短句为主，高效沟通" },
    ],
  },
  {
    key: "formality",
    label: "正式程度",
    options: [
      { value: "formal", name: "正式", desc: "商务规范措辞" },
      { value: "neutral", name: "中性", desc: "介于正式与随意之间" },
      { value: "casual", name: "随意", desc: "轻松口语化" },
    ],
  },
  {
    key: "length_preference",
    label: "长度偏好",
    options: [
      { value: "short", name: "简短", desc: "一两句回复" },
      { value: "medium", name: "适中", desc: "完整表达要点" },
      { value: "long", name: "详细", desc: "充分展开说明" },
    ],
  },
] as const

type RadioKey = (typeof RADIO_GROUPS)[number]["key"]

async function handleSave(): Promise<void> {
  saving.value = true
  try {
    await store.saveGroup("reply-style", { ...form.value })
    ui.pushToast("success", "回复风格已保存")
  } catch (e) {
    ui.pushToast("error", `保存失败：${e instanceof Error ? e.message : "未知错误"}`)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <SettingsPanel title="回复风格" description="HR 消息回复的语气、长度与结构" :dirty="dirty" :saving="saving" @save="handleSave">
    <div
      v-for="group in RADIO_GROUPS"
      :key="group.key"
      class="form-field"
    >
      <span class="form-label">{{ group.label }}</span>
      <div class="form-radio-grid">
        <label
          v-for="opt in group.options"
          :key="opt.value"
          class="form-radio-card"
          :class="{ active: form[group.key as RadioKey] === opt.value }"
        >
          <input
            v-model="form[group.key as RadioKey]"
            type="radio"
            :value="opt.value"
            class="visually-hidden"
          />
          <span class="form-radio-name">{{ opt.name }}</span>
          <span class="form-radio-desc">{{ opt.desc }}</span>
        </label>
      </div>
    </div>

    <hr class="form-divider" />

    <BaseSwitch v-model="form.include_greeting" label="包含问候语" hint="回复开头带问候" />
    <BaseSwitch v-model="form.include_closing" label="包含结束语" hint="回复结尾带落款/结束语" />
  </SettingsPanel>
</template>
