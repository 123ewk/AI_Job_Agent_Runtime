<script setup lang="ts">
// 设置页（设计权威：前端布局 V1.0 §23 左侧菜单 + 右侧内容，样式规范 §6-§12）。
// 菜单分组：LLM 配置 / Agent 策略 / 求职偏好 / 回复风格（对应后端 4 个 /settings/{group}）
// + 简历管理（I12 新增，对接 /api/v1/resumes）。
// 聊天设置/后台监听/数据同步/高级设置 后端暂无接口 → 本页不展示（Phase 3 补齐）。
import { onMounted, ref } from "vue"
import { Bot, Briefcase, Cpu, FileText, MessageSquare } from "lucide-vue-next"
import ErrorState from "../../components/common/ErrorState.vue"
import LlmSettings from "../../components/settings/LlmSettings.vue"
import AgentSettings from "../../components/settings/AgentSettings.vue"
import JobRuleSettings from "../../components/settings/JobRuleSettings.vue"
import ReplyStyleSettings from "../../components/settings/ReplyStyleSettings.vue"
import ResumeSettings from "../../components/settings/ResumeSettings.vue"
import { useSettingsStore } from "../../stores/settings"

const store = useSettingsStore()

const MENU = [
  { key: "llm", label: "LLM 配置", icon: Cpu },
  { key: "agent", label: "Agent 策略", icon: Bot },
  { key: "job-rule", label: "求职偏好", icon: Briefcase },
  { key: "reply-style", label: "回复风格", icon: MessageSquare },
  { key: "resume", label: "简历管理", icon: FileText },
] as const

type MenuKey = (typeof MENU)[number]["key"]
const active = ref<MenuKey>("llm")

onMounted(() => {
  void store.loadAll()
})
</script>

<template>
  <div class="settings-page">
    <header class="page-head">
      <h2 class="page-title">设置</h2>
    </header>

    <!-- 加载失败 → 重试 -->
    <ErrorState v-if="store.error" :message="`设置加载失败：${store.error}`" @retry="store.loadAll()" />

    <!-- 加载中 -->
    <div v-else-if="store.loading" class="page-loading">加载设置中...</div>

    <div v-else class="settings-layout">
      <!-- 左侧设置菜单（§23） -->
      <aside class="settings-menu">
        <nav class="menu" aria-label="设置分组">
          <button
            v-for="item in MENU"
            :key="item.key"
            type="button"
            class="menu-item"
            :class="{ active: active === item.key }"
            @click="active = item.key"
          >
            <component :is="item.icon" :size="18" class="menu-icon" aria-hidden="true" />
            <span class="menu-label">{{ item.label }}</span>
          </button>
        </nav>
      </aside>

      <!-- 右侧内容（渲染当前分组面板） -->
      <div class="settings-content">
        <LlmSettings v-if="active === 'llm'" />
        <AgentSettings v-else-if="active === 'agent'" />
        <JobRuleSettings v-else-if="active === 'job-rule'" />
        <ReplyStyleSettings v-else-if="active === 'reply-style'" />
        <ResumeSettings v-else />
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.page-title {
  margin: 0;
  font-size: var(--fs-page-title);
  font-weight: 600;
  color: var(--color-text-primary);
}

.page-loading {
  padding: var(--space-8) 0;
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--fs-secondary);
}

.settings-layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: var(--space-5);
  align-items: start;
}

/* 左侧菜单（V1.0 §23：竖排分组导航） */
.settings-menu {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: var(--space-2);
  position: sticky;
  top: 0;
}

.menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  height: 40px;
  padding: 0 var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--fs-body);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.menu-item:hover {
  background: var(--color-bg-secondary);
  color: var(--color-primary);
}

.menu-item.active {
  background: rgba(22, 119, 255, 0.08);
  color: var(--color-primary);
  font-weight: 500;
}

.menu-icon {
  color: var(--color-text-tertiary);
  transition: color var(--transition-fast);
}

.menu-item.active .menu-icon,
.menu-item:hover .menu-icon {
  color: var(--color-primary);
}

/* 右侧面板区 */
.settings-content {
  min-width: 0;
}

@media (max-width: 900px) {
  .settings-layout {
    grid-template-columns: 1fr;
  }

  .settings-menu {
    position: static;
  }

  .menu {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .menu-item {
    width: auto;
  }
}
</style>
