<!--
  Settings 面板：完整配置表单，对齐 spec Phase 1。
  职责：LLM 配置、自动回复/投递开关、并发数、回复风格。
  数据流：表单输入 → 点击保存 → settings.update() → chrome.storage.local → 各上下文同步。
  设计选择：显式保存而非自动保存——低频修改场景下，用户对"何时生效"有明确预期。
-->

<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { useSettingsStore } from "../stores/settings"
import type { LLMProvider, ReplyStyle } from "../stores/settings"

const settings = useSettingsStore()
const saving = ref<boolean>(false)
const saved = ref<boolean>(false)

// 本地表单状态，点击保存后才写入 store
const form = ref({
  llmProvider: settings.config.llmProvider,
  apiKey: settings.config.apiKey,
  apiBaseUrl: settings.config.apiBaseUrl ?? "",
  autoReply: settings.config.autoReply,
  autoApply: settings.config.autoApply,
  concurrency: settings.config.concurrency,
  replyStyle: settings.config.replyStyle,
})

// 是否已修改（与 store 中值对比）
const isDirty = computed<boolean>(() => {
  const c = settings.config
  return (
    form.value.llmProvider !== c.llmProvider ||
    form.value.apiKey !== c.apiKey ||
    (form.value.apiBaseUrl ?? "") !== (c.apiBaseUrl ?? "") ||
    form.value.autoReply !== c.autoReply ||
    form.value.autoApply !== c.autoApply ||
    form.value.concurrency !== c.concurrency ||
    form.value.replyStyle !== c.replyStyle
  )
})

const llmOptions: { value: LLMProvider; label: string }[] = [
  { value: "doubao", label: "豆包（Doubao）" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "qwen", label: "通义千问（Qwen）" },
  { value: "deepseek", label: "DeepSeek" },
]

const styleOptions: { value: ReplyStyle; label: string; desc: string }[] = [
  { value: "polite", label: "礼貌正式", desc: "措辞得体，商务风格" },
  { value: "professional", label: "专业干练", desc: "直击要点，专业表达" },
  { value: "concise", label: "简洁明了", desc: "短句为主，高效沟通" },
  { value: "friendly", label: "亲切友好", desc: "温和语气，拉近距离" },
]

/**
 * 保存设置：写入 chrome.storage.local。
 * 成功后显示 2 秒"已保存"提示。
 */
async function handleSave(): Promise<void> {
  if (!isDirty.value) return
  saving.value = true
  saved.value = false
  try {
    await settings.update(form.value)
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } finally {
    saving.value = false
  }
}

/**
 * 恢复默认值：重置表单但不立即保存，用户确认后再点保存。
 */
function handleResetDefaults(): void {
  form.value = {
    llmProvider: "doubao",
    apiKey: "",
    apiBaseUrl: "",
    autoReply: false,
    autoApply: false,
    concurrency: 1,
    replyStyle: "polite",
  }
}

// 并发数增减按钮
function adjustConcurrency(delta: number): void {
  const next = form.value.concurrency + delta
  if (next >= 1 && next <= 10) {
    form.value.concurrency = next
  }
}

onMounted(async () => {
  await settings.init()
  // 初始化后同步本地表单
  form.value = {
    llmProvider: settings.config.llmProvider,
    apiKey: settings.config.apiKey,
    apiBaseUrl: settings.config.apiBaseUrl ?? "",
    autoReply: settings.config.autoReply,
    autoApply: settings.config.autoApply,
    concurrency: settings.config.concurrency,
    replyStyle: settings.config.replyStyle,
  }
})
</script>

<template>
  <div class="settings-panel">
    <!-- 底部操作栏（sticky） -->
    <div class="action-bar">
      <span v-if="isDirty" class="dirty-hint">有未保存的更改</span>
      <span v-else-if="saved" class="saved-hint">✓ 已保存</span>
      <span v-else class="spacer"></span>
      <button
        class="btn btn-save"
        :disabled="!isDirty || saving"
        @click="handleSave"
      >
        {{ saving ? "保存中..." : "保存" }}
      </button>
    </div>

    <!-- LLM 配置 -->
    <section class="section">
      <h3>LLM 配置</h3>

      <div class="field">
        <label>服务商</label>
        <select v-model="form.llmProvider">
          <option v-for="opt in llmOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </div>

      <div class="field">
        <label>API Key</label>
        <input
          v-model="form.apiKey"
          type="password"
          placeholder="sk-..."
          autocomplete="off"
        />
        <p class="hint">密钥仅保存在本地浏览器，不上传服务器</p>
      </div>

      <div class="field">
        <label>API Base URL（可选）</label>
        <input
          v-model="form.apiBaseUrl"
          type="text"
          placeholder="https://api.example.com/v1"
        />
      </div>
    </section>

    <!-- 自动化开关 -->
    <section class="section">
      <h3>自动化</h3>

      <div class="toggle-row">
        <div class="toggle-info">
          <span class="toggle-label">自动回复</span>
          <span class="toggle-desc">普通消息自动回复，敏感问题需确认</span>
        </div>
        <label class="switch">
          <input type="checkbox" v-model="form.autoReply" />
          <span class="slider"></span>
        </label>
      </div>

      <div class="toggle-row">
        <div class="toggle-info">
          <span class="toggle-label">自动投递</span>
          <span class="toggle-desc">评分超过阈值时自动投递简历</span>
        </div>
        <label class="switch">
          <input type="checkbox" v-model="form.autoApply" />
          <span class="slider"></span>
        </label>
      </div>
    </section>

    <!-- 并发数 -->
    <section class="section">
      <h3>任务并发</h3>
      <div class="field">
        <label>同时运行任务数</label>
        <div class="stepper">
          <button type="button" @click="adjustConcurrency(-1)">−</button>
          <span class="stepper-value">{{ form.concurrency }}</span>
          <button type="button" @click="adjustConcurrency(1)">+</button>
        </div>
        <p class="hint">建议 1-3，过高可能触发平台风控</p>
      </div>
    </section>

    <!-- 回复风格 -->
    <section class="section">
      <h3>回复风格</h3>
      <div class="style-grid">
        <label
          v-for="opt in styleOptions"
          :key="opt.value"
          class="style-card"
          :class="{ active: form.replyStyle === opt.value }"
        >
          <input
            type="radio"
            v-model="form.replyStyle"
            :value="opt.value"
            class="visually-hidden"
          />
          <span class="style-name">{{ opt.label }}</span>
          <span class="style-desc">{{ opt.desc }}</span>
        </label>
      </div>
    </section>

    <!-- 危险区 -->
    <section class="section danger-section">
      <h3>其他</h3>
      <button class="btn btn-reset" @click="handleResetDefaults">
        恢复默认设置
      </button>
      <p class="hint">重置表单内容，需点击保存后生效</p>
    </section>

    <!-- 底部留白，避免被 sticky 操作栏遮挡 -->
    <div class="bottom-spacer"></div>
  </div>
</template>

<style scoped>
.settings-panel {
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 13px;
  color: #1a1a1a;
  position: relative;
}

/* 底部操作栏 */
.action-bar {
  position: sticky;
  top: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
  z-index: 10;
}
.dirty-hint {
  font-size: 11px;
  color: #fa8c16;
  margin-right: auto;
}
.saved-hint {
  font-size: 11px;
  color: #52c41a;
  margin-right: auto;
}
.spacer {
  flex: 1;
}
.btn {
  padding: 6px 16px;
  border: 1px solid transparent;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-save {
  background: #1677ff;
  color: #fff;
  border-color: #1677ff;
}
.btn-save:hover:not(:disabled) {
  background: #0958d9;
}
.btn-save:disabled {
  background: #d9d9d9;
  border-color: #d9d9d9;
  cursor: not-allowed;
}

.section {
  padding: 0 16px;
  margin-top: 16px;
}
.section h3 {
  font-size: 13px;
  font-weight: 600;
  margin: 0 0 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid #f0f0f0;
  color: #262626;
}

.field {
  margin-bottom: 12px;
}
.field label {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #595959;
}
.field input[type="text"],
.field input[type="password"],
.field select {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  font-size: 13px;
  box-sizing: border-box;
  transition: border-color 0.2s;
}
.field input:focus,
.field select:focus {
  outline: none;
  border-color: #1677ff;
}
.hint {
  margin: 4px 0 0;
  font-size: 11px;
  color: #8c8c8c;
}

/* Toggle Switch */
.toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f5f5f5;
}
.toggle-row:last-child {
  border-bottom: none;
}
.toggle-info {
  display: flex;
  flex-direction: column;
}
.toggle-label {
  font-size: 13px;
  font-weight: 500;
}
.toggle-desc {
  font-size: 11px;
  color: #8c8c8c;
  margin-top: 2px;
}
.switch {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
}
.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}
.slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: #d9d9d9;
  border-radius: 20px;
  transition: 0.2s;
}
.slider::before {
  content: "";
  position: absolute;
  height: 14px;
  width: 14px;
  left: 3px;
  bottom: 3px;
  background: #fff;
  border-radius: 50%;
  transition: 0.2s;
}
.switch input:checked + .slider {
  background: #1677ff;
}
.switch input:checked + .slider::before {
  transform: translateX(16px);
}

/* Stepper */
.stepper {
  display: flex;
  align-items: center;
  gap: 0;
}
.stepper button {
  width: 28px;
  height: 28px;
  border: 1px solid #d9d9d9;
  background: #fff;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}
.stepper button:first-child {
  border-radius: 6px 0 0 6px;
}
.stepper button:last-child {
  border-radius: 0 6px 6px 0;
}
.stepper button:hover {
  background: #f5f5f5;
}
.stepper-value {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  height: 28px;
  border-top: 1px solid #d9d9d9;
  border-bottom: 1px solid #d9d9d9;
  font-size: 13px;
  font-weight: 500;
}

/* Style Grid */
.style-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.style-card {
  display: flex;
  flex-direction: column;
  padding: 10px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.style-card:hover {
  border-color: #69b1ff;
}
.style-card.active {
  border-color: #1677ff;
  background: #e6f4ff;
}
.style-name {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 2px;
}
.style-desc {
  font-size: 10px;
  color: #8c8c8c;
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

/* 危险区 */
.danger-section .btn-reset {
  background: #fff;
  color: #8c8c8c;
  border: 1px solid #d9d9d9;
  width: 100%;
  padding: 8px;
}
.danger-section .btn-reset:hover {
  color: #cf1322;
  border-color: #ffa39e;
}

.bottom-spacer {
  height: 20px;
}
</style>
