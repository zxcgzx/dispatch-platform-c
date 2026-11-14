<script setup lang="ts">
// 网架拓扑图：905 节点 / 1000 支路，坐标由后端预算（spring_layout 固定种子，缓存），前端不再跑力导向。
// 节点按电压等级着色；支路按负载率着色，停运支路画虚线，孤岛型支路画细一些；可只看网状部分（225 条）；
// 有逐时段结果时用时段滑块切换；可搜索 B43、L155 并定位；点击节点或支路显示详情卡。
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LinesChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '@/api/client'
import type { SolveResult, Topo } from '@/types/later'

echarts.use([LinesChart, ScatterChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{ result: SolveResult | null; outageRows?: string[] }>()
const topo = ref<Topo | null>(null)
const el = ref<HTMLElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
const meshedOnly = ref(false)
const period = ref(1)
const search = ref('')
const detail = ref<any>(null)
const hasPeriods = computed(() => !!props.result && props.result.status !== 'mock' && !!(props.result.branch_status || props.result.branch_flow))
const nP = computed(() => props.result?.periods ?? 16)

const kvColor: Record<number, string> = { 500: '#c0392b', 220: '#e67e22', 110: '#2f6fde', 35: '#2a9d4a', 10: '#8e6bbf', 6: '#8a8d91' }
function rhoColor(r: number | null) {
  if (r === null) return '#b9b6ab'
  if (r >= 1) return '#d03b3b'
  if (r >= 0.8) return '#e67e22'
  if (r >= 0.5) return '#e8b630'
  return '#7aa6d8'
}
// 每条支路当前时段的状态与负载率（有结果用结果；否则用断面）
const live = computed(() => {
  const out: Record<string, { on: boolean; rho: number | null }> = {}
  const r = props.result
  const outage = new Set(props.outageRows ?? [])
  topo.value?.branches.forEach((b) => {
    let on = b.in_service && !outage.has(b.id)
    let rho = b.load_ratio
    if (hasPeriods.value && r) {
      const st = r.branch_status?.[b.id]
      if (st) on = st[period.value - 1] === 1
      const f = r.branch_flow?.[b.id]
      if (f?.pf?.length && f.qf?.length && f.pt?.length && f.qt?.length && b.rate_a > 0) {
        const i = period.value - 1
        rho = Math.max(Math.hypot(f.pf[i], f.qf[i]), Math.hypot(f.pt[i], f.qt[i])) / b.rate_a
      }
    }
    out[b.id] = { on, rho }
  })
  return out
})

let loading: Promise<void> | null = null
function load() {
  loading ??= (async () => {
    topo.value = await api.get<Topo>('/topology')
    draw()
  })()
  return loading
}
function draw() {
  if (!topo.value || !el.value) return
  if (!chart.value) {
    chart.value = echarts.init(el.value)
    chart.value.on('click', (p: any) => {
      if (p.seriesName === 'nodes') detail.value = { ...topo.value!.nodes[p.dataIndex], kind: 'bus' }
      else if (p.seriesName === 'branches') detail.value = { ...p.data.br, ...live.value[p.data.br.id], kind: 'branch' }
    })
  }
  const nodes = topo.value.nodes
  const pos = new Map(nodes.map((n) => [n.id, [n.x, n.y]]))
  const L = lines.value
  // 支路：按负载率着色；停运虚线；孤岛型支路更细
  const lineData = L.map((b) => {
    const s = live.value[b.id]
    return {
      br: b, coords: [pos.get(b.from), pos.get(b.to)],
      lineStyle: { color: s.on ? rhoColor(s.rho) : '#d03b3b', width: b.isolating ? 0.6 : 1.4, type: s.on ? 'solid' : 'dashed', opacity: s.on ? 0.85 : 1 },
    }
  })
  chart.value.setOption({
    animation: false,
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => (p.seriesName === 'nodes' ? `${p.data.name}<br/>${p.data.kv}kV · PD ${p.data.pd} MW · VM ${p.data.vm}` : p.seriesName === 'branches' ? tipOf(p.data.br) : ''),
    },
    grid: { left: 6, right: 6, top: 6, bottom: 6 },
    xAxis: { type: 'value', show: false, min: -20, max: 1020 },
    yAxis: { type: 'value', show: false, min: -20, max: 1020 },
    dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }, { type: 'inside', yAxisIndex: 0, filterMode: 'none' }],
    series: [
      { name: 'branches', type: 'lines', coordinateSystem: 'cartesian2d', polyline: false, z: 1, silent: false, large: false, data: lineData },
      {
        name: 'nodes', type: 'scatter', z: 3, symbolSize: (v: any) => (v[3] >= 220 ? 6 : v[3] >= 110 ? 4 : 2.5),
        data: nodes.map((n) => ({ name: n.id, value: [n.x, n.y, n.id, n.kv], kv: n.kv, pd: n.pd, vm: n.vm, itemStyle: { color: kvColor[n.kv] ?? '#888' } })),
      },
    ],
  }, true)
}
const lines = computed(() => (topo.value?.branches ?? []).filter((b) => !meshedOnly.value || !b.isolating))
function tipOf(b: any) {
  const s = live.value[b.id]
  return `${b.id}（${b.from.slice(1)}–${b.to.slice(1)}，${b.kv}kV）<br/>${s.on ? '在运' : '停运'} · 负载率 ${s.rho === null ? '不限' : (s.rho * 100).toFixed(1) + '%'}`
}
onMounted(() => { void load(); window.addEventListener('resize', onResize); setTimeout(onResize, 200) })
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); chart.value?.dispose() })
function onResize() { if (el.value && el.value.clientWidth > 10 && el.value.clientHeight > 10) chart.value?.resize() }
watch([meshedOnly, period, () => props.result, () => props.outageRows], () => draw())

async function locate() {
  await load()
  const q = search.value.trim().toUpperCase()
  if (!topo.value || !q) return
  const n = topo.value.nodes.find((x) => x.id === q)
  const b = topo.value.branches.find((x) => x.id === q)
  if (n) detail.value = { ...n, kind: 'bus' }
  else if (b) detail.value = { ...b, ...live.value[b.id], kind: 'branch' }
  else detail.value = { kind: 'none', q }
  chart.value?.dispatchAction({ type: 'showTip', seriesIndex: n ? 1 : 0, dataIndex: n ? topo.value.nodes.indexOf(n) : 0 })
}
defineExpose({ load })
</script>

<template>
  <div class="tg" data-testid="topo-graph">
    <div class="bar row">
      <el-switch v-model="meshedOnly" active-text="只看网状部分（225 条）" size="small" data-testid="meshed-switch" />
      <el-input v-model="search" size="small" placeholder="搜索 B43 / L155 并定位" style="width: 200px" data-testid="topo-search" @keyup.enter="locate" />
      <el-button size="small" @click="locate">定位</el-button>
      <template v-if="hasPeriods">
        <span class="sub">时段</span>
        <el-slider v-model="period" :min="1" :max="nP" :show-tooltip="true" style="width: 220px" data-testid="period-slider" />
        <b>{{ period }}</b>
      </template>
      <span v-else class="sub">无逐时段结果：显示调整前断面</span>
      <span class="grow" />
      <span class="legend"><i v-for="(c, k) in kvColor" :key="k" :style="{ background: c }" />{{ Object.keys(kvColor).join('/') }} kV</span>
    </div>
    <div class="wrap">
      <div ref="el" class="cv" data-testid="topo-canvas" />
      <div v-if="detail" class="detail card card-pad" data-testid="topo-detail">
        <el-button size="small" text class="x" @click="detail = null">×</el-button>
        <template v-if="detail.kind === 'bus'">
          <b>{{ detail.id }}</b>
          <div class="sub">电压等级 {{ detail.kv }}kV</div>
          <div>PD {{ detail.pd }} MW · VM {{ detail.vm }}</div>
        </template>
        <template v-else-if="detail.kind === 'branch'">
          <b>{{ detail.id }}</b>（{{ detail.from.slice(1) }}–{{ detail.to.slice(1) }}，{{ detail.kv }}kV）
          <div class="sub">{{ detail.transformer ? '变压器支路' : '线路' }} · {{ detail.isolating ? '孤岛型（一断开就形成孤岛）' : '网状部分' }} · 并联 {{ detail.parallel }} 条</div>
          <div>{{ detail.on ? '在运' : '停运' }} · RATE_A {{ detail.rate_a || '不限' }} · 负载率 {{ detail.rho === null ? '不限' : (detail.rho * 100).toFixed(1) + '%' }}</div>
        </template>
        <div v-else class="lv-warn">没有找到 {{ detail.q }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bar { flex-wrap: wrap; margin-bottom: 8px; }
.wrap { position: relative; }
.cv { height: 560px; border: 1px solid var(--c-hairline); border-radius: var(--radius); background: #fcfcfb; }
.detail { position: absolute; right: 12px; top: 12px; width: 280px; font-size: var(--fs-sm); }
.x { position: absolute; right: 2px; top: 2px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 3px; }
</style>
