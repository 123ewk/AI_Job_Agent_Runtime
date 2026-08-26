<script setup lang="ts">
// LLM 配置面板（设计权威：前端布局 V1.0 §24，后端 /settings/llm）。
// 字段：provider/base_url/model/temperature + api_key（保存必填，防止空串覆盖真实密钥）。
// 「测试连接」调 /settings/validate-llm（后端当前为占位实现）。
import { computed, ref, watch } from "vue"
import { useSettingsStore, type LlmConfig } from "../../stores/settings"
import { useUiStore } from "../../stores/ui"
import SettingsPanel from "./SettingsPanel.vue"
import "./SettingsForm.css"

const store = useSettingsStore()
const ui = useUiStore()

interface LlmForm {
  provider: string
  base_url: string
  model: string
  api_key: string
  temperature: number
}

function toForm(cfg: LlmConfig | null): LlmForm {
  return {
    provider: cfg?.provider ?? "openai",
    base_url: cfg?.base_url ?? "",
    model: cfg?.model ?? "",
    api_key: "",
    temperature: cfg?.temperature ?? 0.7,
  }
}

const form = ref<LlmForm>(toForm(store.llm))
// store 数据到达/保存回写时同步表单（面板在 loadAll 完成后才挂载，此处兜底）
watch(
  () => store.llm,
  (v) => {
    if (v) form.value = toForm(v)
  },
)

const dirty = computed(
  () =>
    store.llm !== null &&
    (form.value.provider !== store.llm!.provider ||
      form.value.base_url !== (store.llm!.base_url ?? "") ||
      form.value.model !== store.llm!.model ||
      form.value.temperature !== store.llm!.temperature ||
      form.value.api_key.length > 0),
)

const PROVIDER_OPTIONS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "doubao", label: "豆包（Doubao）" },
  { value: "qwen", label: "通义千问（Qwen）" },
  { value: "deepseek", label: "DeepSeek" },
]

const saving = ref(false)
const validating = ref(false)
const validateResult = ref<string | null>(null)

async function handleSave(): Promise<void> {
  if (!form.value.api_key.trim()) {
    // 后端落库时仅非空 api_key 才加密存储，空串会覆盖真实密钥 → 保存前置校验
    ui.pushToast("error", "请填写 API Key 再保存（留空将覆盖当前密钥）")
    return
  }
  saving.value = true
  try {
    await store.saveGroup("llm", {
      provider: form.value.provider,
      base_url: form.value.base_url || null,
      model: form.value.model,
      api_key: form.value.api_key,
      temperature: form.value.temperature,
    })
    ui.pushToast("success", "LLM 配置已保存")
  } catch (e) {
    ui.pushToast("error", `保存失败：${e instanceof Error ? e.message : "未知错误"}`)
  } finally {
    saving.value = false
  }
}

async function handleValidate(): Promise<void> {
  // 先本地校验：后端判定依赖表单当前填写的 api_key（不读已保存值），
  // 为空直接提示，不发请求、不要求先保存。
  if (!form.value.api_key.trim()) {
    ui.pushToast("error", "请先填写 API Key 再测试连接")
    return
  }
  validating.value = true
  validateResult.value = null
  try {
    const res = await store.validateLlm({
      provider: form.value.provider,
      base_url: form.value.base_url || null,
      model: form.value.model,
      api_key: form.value.api_key,
      temperature: form.value.temperature,
    })
    validateResult.value = res.ok ? "连接正常" : `连接失败：${res.detail}`
    ui.pushToast(res.ok ? "success" : "error", validateResult.value)
  } catch (e) {
    const msg = e instanceof Error ? e.message : "测试失败"
    validateResult.value = msg
    ui.pushToast("error", msg)
  } finally {
    validating.value = false
  }
}
</script>

<template>
  <SettingsPanel title="LLM 配置" description="大模型服务商、模型与密钥配置" :dirty="dirty" :saving="saving" @save="handleSave">
    <div class="form-grid">
      <div class="form-field">
        <label class="form-label" for="llm-provider">服务商</label>
        <select id="llm-provider" v-model="form.provider" class="form-select">
          <option v-for="opt in PROVIDER_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
      </div>
      <div class="form-field">
        <label class="form-label" for="llm-model">模型</label>
        <input id="llm-model" v-model="form.model" class="form-input" type="text" placeholder="gpt-4o-mini" />
      </div>
    </div>

    <div class="form-field">
      <label class="form-label" for="llm-base-url">API Base URL（可选）</label>
      <input id="llm-base-url" v-model="form.base_url" class="form-input" type="text" placeholder="https://api.example.com/v1" />
      <p class="form-hint">兼容代理/中转场景；留空使用服务商默认地址</p>
    </div>

    <div class="form-field">
      <label class="form-label" for="llm-apikey">API Key</label>
      <input
        id="llm-apikey"
        v-model="form.api_key"
        class="form-input"
        type="password"
        :placeholder="store.llm?.api_key_masked ?? 'sk-...'"
        autocomplete="off"
      />
      <p class="form-hint">当前值仅显示掩码（{{ store.llm?.api_key_masked ?? "未配置" }}）；保存需填写新 Key</p>
    </div>

    <div class="form-field">
      <label class="form-label" for="llm-temp">采样温度</label>
      <input
        id="llm-temp"
        v-model.number="form.temperature"
        class="form-input"
        type="number"
        min="0"
        max="2"
        step="0.1"
      />
      <p class="form-hint">0 到 2，越高越有创造性（默认 0.7）</p>
    </div>

    <button type="button" class="test-btn" :disabled="validating" @click="handleValidate">
      {{ validating ? "测试中..." : "测试连接" }}
    </button>
    <p v-if="validateResult" class="validate-result">{{ validateResult }}</p>
  </SettingsPanel>
</template>

<style scoped>
.test-btn {
  margin-top: var(--space-2);
  padding: 0 var(--space-4);
  height: 32px;
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-sm);
  background: var(--color-bg-card);
  color: var(--color-primary);
  font-size: var(--fs-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.test-btn:hover:not(:disabled) {
  background: rgba(22, 119, 255, 0.05);
}

.test-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.validate-result {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}
</style>
