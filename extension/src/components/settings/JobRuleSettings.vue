<script setup lang="ts">
// 求职偏好面板（设计权威：前端布局 V1.0 §27，后端 /settings/job-rule）。
// 字段：薪资区间/期望地点/加班/外包/异地。未配置项（None）即 Approval 触发条件（后端语义）。
import { computed, ref, watch } from "vue"
import { useSettingsStore, type JobRuleConfig } from "../../stores/settings"
import { useUiStore } from "../../stores/ui"
import SettingsPanel from "./SettingsPanel.vue"
import BaseSwitch from "./BaseSwitch.vue"
import "./SettingsForm.css"

const store = useSettingsStore()
const ui = useUiStore()

interface JobRuleForm {
  min_salary: string
  max_salary: string
  /** 逗号分隔字符串，保存时转数组 */
  preferred_locations: string
  overtime_allowed: boolean
  outsourcing_allowed: boolean
  offsite_allowed: boolean
}

function toForm(cfg: JobRuleConfig | null): JobRuleForm {
  return {
    min_salary: cfg?.min_salary != null ? String(cfg.min_salary) : "",
    max_salary: cfg?.max_salary != null ? String(cfg.max_salary) : "",
    preferred_locations: cfg?.preferred_locations?.join(", ") ?? "",
    overtime_allowed: cfg?.overtime_allowed ?? false,
    outsourcing_allowed: cfg?.outsourcing_allowed ?? false,
    offsite_allowed: cfg?.offsite_allowed ?? false,
  }
}

const form = ref<JobRuleForm>(toForm(store.jobRule))
watch(
  () => store.jobRule,
  (v) => {
    if (v) form.value = toForm(v)
  },
)

const dirty = computed(
  () =>
    store.jobRule !== null &&
    (form.value.min_salary !== (store.jobRule!.min_salary != null ? String(store.jobRule!.min_salary) : "") ||
      form.value.max_salary !== (store.jobRule!.max_salary != null ? String(store.jobRule!.max_salary) : "") ||
      form.value.preferred_locations !== (store.jobRule!.preferred_locations?.join(", ") ?? "") ||
      form.value.overtime_allowed !== store.jobRule!.overtime_allowed ||
      form.value.outsourcing_allowed !== store.jobRule!.outsourcing_allowed ||
      form.value.offsite_allowed !== store.jobRule!.offsite_allowed),
)

const saving = ref(false)

async function handleSave(): Promise<void> {
  saving.value = true
  try {
    await store.saveGroup("job-rule", {
      min_salary: form.value.min_salary ? Number(form.value.min_salary) : null,
      max_salary: form.value.max_salary ? Number(form.value.max_salary) : null,
      preferred_locations: form.value.preferred_locations
        ? form.value.preferred_locations.split(",").map((s) => s.trim()).filter(Boolean)
        : null,
      overtime_allowed: form.value.overtime_allowed,
      outsourcing_allowed: form.value.outsourcing_allowed,
      offsite_allowed: form.value.offsite_allowed,
    })
    ui.pushToast("success", "求职偏好已保存")
  } catch (e) {
    ui.pushToast("error", `保存失败：${e instanceof Error ? e.message : "未知错误"}`)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <SettingsPanel title="求职偏好" description="薪资、地点与接受条件；留空项视为需人工确认" :dirty="dirty" :saving="saving" @save="handleSave">
    <div class="form-grid">
      <div class="form-field">
        <label class="form-label" for="job-min">最低期望月薪（K）</label>
        <input id="job-min" v-model="form.min_salary" class="form-input" type="number" min="0" placeholder="15" />
      </div>
      <div class="form-field">
        <label class="form-label" for="job-max">最高期望月薪（K）</label>
        <input id="job-max" v-model="form.max_salary" class="form-input" type="number" min="0" placeholder="35" />
      </div>
    </div>

    <div class="form-field">
      <label class="form-label" for="job-loc">期望地点</label>
      <input id="job-loc" v-model="form.preferred_locations" class="form-input" type="text" placeholder="北京, 上海, 深圳" />
      <p class="form-hint">逗号分隔多个城市</p>
    </div>

    <hr class="form-divider" />

    <BaseSwitch v-model="form.overtime_allowed" label="接受加班" hint="开启后接受加班岗位" />
    <BaseSwitch v-model="form.outsourcing_allowed" label="接受外包" hint="开启后接受外包岗位" />
    <BaseSwitch v-model="form.offsite_allowed" label="接受异地办公" hint="开启后接受异地办公岗位" />
  </SettingsPanel>
</template>
