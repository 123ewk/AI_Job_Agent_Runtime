<script setup lang="ts">
// 简历管理面板（设计权威：前端布局 V1.0 §30 简历管理 + §23 设置菜单）。
// 职责：当前简历列表（名称/上传时间/状态/默认徽标/摘要预览）+ 导入/查看/设默认/删除。
// 后端契约：I12 新增 /api/v1/resumes（JSON 文本导入，非 multipart）。
// V1 如实标注：
//   - 导入仅支持文本文件（.txt/.md），docx/pdf 解析待后端文件管线（MinIO + 解析服务）
//   - summary_preview 后端恒为 None（Agent 摘要管线未接线）→ gap-note
//   - 无「原地更新」端点：重复导入 = 新建一条简历（V1 接受）
import { onMounted, ref } from "vue"
import { Check, Eye, FileText, Trash2, Upload } from "lucide-vue-next"
import EmptyState from "../common/EmptyState.vue"
import ErrorState from "../common/ErrorState.vue"
import { formatDate } from "../../lib/time"
import { useResumeStore, type ResumeItem } from "../../stores/resume"
import { useUiStore } from "../../stores/ui"

const store = useResumeStore()
const ui = useUiStore()

const fileInput = ref<HTMLInputElement | null>(null)
const importing = ref(false)
const detailLoading = ref(false)
const expandedId = ref<number | null>(null)
const detailContent = ref("")

onMounted(() => {
  void store.fetchList()
})

function openFilePicker(): void {
  fileInput.value?.click()
}

const TEXT_EXTENSIONS = ["txt", "md", "markdown"]

async function handleFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = "" // 允许再次选择同一文件
  if (!file) return

  const ext = file.name.split(".").pop()?.toLowerCase() ?? ""
  if (!TEXT_EXTENSIONS.includes(ext)) {
    ui.pushToast("error", "暂只支持文本文件导入（.txt/.md）")
    return
  }
  if (file.size > 1_000_000) {
    ui.pushToast("error", "文件过大（>1MB），请精简后导入")
    return
  }

  importing.value = true
  try {
    const content = await readFileAsText(file)
    const name = file.name.replace(/\.[^.]+$/, "")
    await store.create(name, content.trim())
    ui.pushToast("success", `简历「${name}」已导入`)
  } catch (e) {
    ui.pushToast("error", `导入失败：${e instanceof Error ? e.message : "未知错误"}`)
  } finally {
    importing.value = false
  }
}

/** FileReader 封装：文本文件按 UTF-8 读取（Promise 化） */
function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "")
    reader.onerror = () => reject(new Error("文件读取失败"))
    reader.readAsText(file, "utf-8")
  })
}

/** 查看详情：展开/收起，内容按需拉取（列表不带原文，控制响应体大小） */
async function toggleDetail(item: ResumeItem): Promise<void> {
  if (expandedId.value === item.id) {
    expandedId.value = null
    return
  }
  detailLoading.value = true
  try {
    const detail = await store.fetchDetail(item.id)
    detailContent.value = detail.content ?? "暂无内容"
    expandedId.value = item.id
  } catch (e) {
    ui.pushToast("error", `查看失败：${e instanceof Error ? e.message : "未知错误"}`)
  } finally {
    detailLoading.value = false
  }
}

async function handleActivate(item: ResumeItem): Promise<void> {
  try {
    await store.activate(item.id)
    ui.pushToast("success", `「${item.name}」已设为默认简历`)
  } catch (e) {
    ui.pushToast("error", `设置失败：${e instanceof Error ? e.message : "未知错误"}`)
  }
}

async function handleDelete(item: ResumeItem): Promise<void> {
  const ok = window.confirm(`确定删除简历「${item.name}」？删除后不可恢复。`)
  if (!ok) return
  try {
    await store.remove(item.id)
    if (expandedId.value === item.id) expandedId.value = null
    ui.pushToast("success", `「${item.name}」已删除`)
  } catch (e) {
    ui.pushToast("error", `删除失败：${e instanceof Error ? e.message : "未知错误"}`)
  }
}
</script>

<template>
  <section class="resume-settings">
    <header class="panel-head">
      <div class="head-text">
        <h3 class="panel-title">简历管理</h3>
        <p class="panel-desc">上传简历文本，Agent 将基于它进行岗位匹配与投递（V1 仅支持文本文件）</p>
      </div>
      <button type="button" class="btn-import" :disabled="importing" @click="openFilePicker">
        <Upload :size="16" aria-hidden="true" />
        {{ importing ? "导入中..." : "导入简历" }}
      </button>
      <input ref="fileInput" type="file" accept=".txt,.md,.markdown" class="visually-hidden" @change="handleFileChange" />
    </header>

    <ErrorState v-if="store.error" :message="`简历加载失败：${store.error}`" @retry="store.fetchList()" />

    <div v-else-if="store.loading" class="page-loading">加载简历中...</div>

    <EmptyState v-else-if="store.resumes.length === 0" title="暂无简历" hint="点击右上角「导入简历」上传文本文件（.txt/.md）">
      <button type="button" class="btn-import" @click="openFilePicker"><Upload :size="16" aria-hidden="true" />导入简历</button>
    </EmptyState>

    <ul v-else class="resume-list">
      <li v-for="item in store.resumes" :key="item.id" class="resume-card">
        <div class="card-main">
          <div class="card-title-row">
            <FileText :size="18" class="file-icon" aria-hidden="true" />
            <span class="resume-name">{{ item.name }}</span>
            <span v-if="item.isDefault" class="badge badge-default"><Check :size="12" aria-hidden="true" />默认</span>
            <span class="badge badge-version">v{{ item.version }}</span>
          </div>
          <div class="card-meta">
            <span>上传于 {{ formatDate(item.createdAt) }}</span>
            <span class="meta-sep">·</span>
            <span>状态：{{ item.status === "active" ? "使用中" : item.status }}</span>
          </div>
          <p class="summary">
            摘要：<template v-if="item.summaryPreview">{{ item.summaryPreview }}</template>
            <span v-else class="summary-gap">需 Agent 分析后出现</span>
          </p>
        </div>

        <div class="card-actions">
          <button type="button" class="action-btn" @click="toggleDetail(item)">
            <Eye :size="16" aria-hidden="true" />{{ expandedId === item.id ? "收起" : "查看" }}
          </button>
          <button v-if="!item.isDefault" type="button" class="action-btn" @click="handleActivate(item)">设为默认</button>
          <button type="button" class="action-btn danger" @click="handleDelete(item)">
            <Trash2 :size="16" aria-hidden="true" />删除
          </button>
        </div>

        <!-- 查看展开：显示简历原文（按需拉取） -->
        <div v-if="expandedId === item.id" class="detail-box">
          <div v-if="detailLoading" class="detail-loading">加载原文中...</div>
          <pre v-else class="detail-content">{{ detailContent }}</pre>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.resume-settings {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.panel-title {
  margin: 0;
  font-size: var(--fs-card-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.panel-desc {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.page-loading {
  padding: var(--space-8) 0;
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--fs-secondary);
}

.btn-import {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
  padding: 0 var(--space-4);
  height: 32px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  font-size: var(--fs-secondary);
  font-weight: 500;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.btn-import:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.btn-import:disabled {
  background: var(--color-text-disabled);
  cursor: not-allowed;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

.resume-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.resume-card {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.resume-card:last-child {
  border-bottom: none;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.file-icon {
  color: var(--color-primary);
}

.resume-name {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--color-text-primary);
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 500;
}

.badge-default {
  background: rgba(34, 197, 94, 0.12);
  color: var(--color-success);
}

.badge-version {
  background: var(--color-bg-secondary);
  color: var(--color-text-tertiary);
}

.card-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-1);
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.meta-sep {
  color: var(--color-border-strong);
}

.summary {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-secondary);
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.summary-gap {
  color: var(--color-text-disabled);
}

.card-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-3);
  height: 28px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-size: var(--fs-aux);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.action-btn:hover:not(:disabled) {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.action-btn.danger:hover {
  border-color: var(--color-danger);
  color: var(--color-danger);
}

.detail-box {
  margin-top: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
}

.detail-loading {
  padding: var(--space-3) 0;
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--fs-aux);
}

.detail-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: var(--fs-secondary);
  line-height: 1.6;
  color: var(--color-text-primary);
}
</style>
