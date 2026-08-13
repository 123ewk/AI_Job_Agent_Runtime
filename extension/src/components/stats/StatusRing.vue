<script setup lang="ts">
// 环形状态分布（设计权威：[[stats-page-design-feedback]]——岗位状态环形图，直径 130~160px，中心显示总数）。
// 纯 SVG 实现、零图表库依赖（项目未引入 ECharts/Chart.js，不为此页新增依赖）。
// 原理：每段画一个 <circle>，stroke-dasharray = [段长, 周长-段长] 只显示该段圆弧；
//       整体 rotate(-90deg) 使起始于 12 点并顺时针；offset 逐段累积保证无缝拼接。
// 0 数据：只画浅灰空轨，中心仍显示总数（保持布局）；「无岗位」的 EmptyState 由父级决定。
import { computed } from "vue"

/** 环形分段（label 用于右侧图例；color 为 CSS 变量引用，如 var(--color-primary)） */
export interface RingSegment {
  label: string
  count: number
  color: string
}

const props = defineProps<{
  segments: RingSegment[]
  /** 中心主数字（岗位状态处传全量岗位总数） */
  total: number
  /** 中心下方说明（如「岗位」） */
  caption: string
}>()

const SIZE = 140
const STROKE = 14
// viewBox 为 140×140，圆心恒为 70（rotate 的旋转中心同步用 70）
const RADIUS = (SIZE - STROKE) / 2
const CIRC = 2 * Math.PI * RADIUS

/** 参与绘制的分段（count>0）；length = 占段长，offset = 距 12 点的起始位移 */
const arcs = computed(() => {
  const visible = props.segments.filter((s) => s.count > 0)
  const sum = visible.reduce((acc, s) => acc + s.count, 0)
  if (sum === 0) return []
  let start = 0
  return visible.map((s) => {
    const len = (s.count / sum) * CIRC
    const arc = { ...s, len, offset: -start }
    start += len
    return arc
  })
})
</script>

<template>
  <div class="status-ring">
    <div class="ring-wrap">
      <svg class="ring-svg" :viewBox="`0 0 ${SIZE} ${SIZE}`" role="img" aria-label="岗位状态分布">
        <!-- 空轨：无数据时仍保持圆环布局 -->
        <circle class="ring-track" :cx="SIZE / 2" :cy="SIZE / 2" :r="RADIUS" />
        <circle
          v-for="(arc, i) in arcs"
          :key="i"
          class="ring-seg"
          :cx="SIZE / 2"
          :cy="SIZE / 2"
          :r="RADIUS"
          :stroke="arc.color"
          :stroke-dasharray="`${arc.len} ${CIRC - arc.len}`"
          :stroke-dashoffset="arc.offset"
          transform="rotate(-90 70 70)"
        />
      </svg>
      <div class="ring-center">
        <span class="ring-total">{{ total }}</span>
        <span class="ring-caption">{{ caption }}</span>
      </div>
    </div>

    <!-- 右侧状态图例（0 数据时灰点，保持行布局） -->
    <ul class="ring-legend">
      <li v-for="seg in segments" :key="seg.label" class="legend-item">
        <span class="legend-dot" :style="{ background: seg.count > 0 ? seg.color : 'var(--color-border)' }" />
        <span class="legend-label">{{ seg.label }}</span>
        <span class="legend-count">{{ seg.count }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.status-ring {
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.ring-wrap {
  position: relative;
  width: 140px;
  height: 140px;
  flex-shrink: 0;
}

.ring-svg {
  width: 100%;
  height: 100%;
}

.ring-track,
.ring-seg {
  fill: none;
  stroke-width: 14;
}

.ring-track {
  stroke: var(--color-bg-secondary);
}

.ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.ring-total {
  font-size: 28px;
  font-weight: 600;
  line-height: 1;
  color: var(--color-text-primary);
}

.ring-caption {
  margin-top: 4px;
  font-size: var(--fs-aux);
  color: var(--color-text-tertiary);
}

.ring-legend {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 130px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-secondary);
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-label {
  flex: 1;
  color: var(--color-text-secondary);
}

.legend-count {
  font-weight: 600;
  color: var(--color-text-primary);
}
</style>
