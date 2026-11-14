<script setup lang="ts">
// 电网地图：大理州真实行政区划（12 个县市）为底图，网架叠加其上。
// 节点位置按拓扑落在各县范围内（示意，非真实站址）；支路按电压等级着色，停运 / 方案断开画红色虚线；
// 有求解结果时叠加方案；可筛选电压等级、搜索 B / L 编号定位。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LinesChart, MapChart, ScatterChart, EffectScatterChart } from 'echarts/charts'
import { GeoComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '@/api/client'
import type { SolveResult, Topo } from '@/types/later'

echarts.use([LinesChart, MapChart, ScatterChart, EffectScatterChart, GeoComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

const props = defineProps<{ result?: SolveResult | null; outageRows?: string[]; height?: number }>()
const el = ref<HTMLElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
const topo = ref<Topo | null>(null)
const geo = ref<{ pos: Record<string, [number, number]>; county: Record<string, string>; county_counts: Record<string, number> } | null>(null)
const geojson = ref<any>(null)
const kvSel = ref<number[]>([500, 220, 110])
const showLow = ref(false)
const search = ref('')
const detail = ref<any>(null)
const loaded = ref(false)
const loadError = ref('')
const useSvg = ref(!/[?&]svg=0/.test(location.search))   // 默认用纯 SVG（最稳）；可切到 ECharts（可缩放拖动）
// 纯 SVG 兜底：不依赖 ECharts / canvas，行政区划多边形 + 线路 + 站点
const svgData = computed(() => {
  if (!geojson.value || !topo.value || !geo.value) return null
  let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9
  const walk = (c: any) => { if (typeof c[0] === 'number') { x0 = Math.min(x0, c[0]); x1 = Math.max(x1, c[0]); y0 = Math.min(y0, c[1]); y1 = Math.max(y1, c[1]) } else c.forEach(walk) }
  geojson.value.features.forEach((f: any) => walk(f.geometry.coordinates))
  const W = 1000, k = Math.cos(((y0 + y1) / 2) * Math.PI / 180), sc = W / ((x1 - x0) * k), H = (y1 - y0) * sc
  const P = (c: number[]) => [((c[0] - x0) * k * sc).toFixed(1), ((y1 - c[1]) * sc).toFixed(1)]
  const ring = (r: number[][]) => 'M' + r.map((c) => P(c).join(',')).join('L') + 'Z'
  const paths = geojson.value.features.map((f: any) => {
    const g = f.geometry, polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates
    const [lx, ly] = P(f.properties.center ?? f.properties.cp ?? polys[0][0][0])
    return { name: f.properties.name, d: polys.map((pl: number[][][]) => pl.map(ring).join('')).join(''), lx, ly }
  })
  const sel = new Set(kvSel.value), pos = geo.value.pos
  const ok = (kv: number) => sel.has(kv) || (showLow.value && kv < 110)
  const ids = new Set(topo.value.nodes.filter((n) => ok(n.kv)).map((n) => n.id))
  const lines = topo.value.branches.filter((b) => ok(b.kv) && ids.has(b.from) && ids.has(b.to) && pos[b.from] && pos[b.to]).map((b) => {
    const a = P(pos[b.from]), c = P(pos[b.to]), off = opened.value.has(b.id) || !b.in_service
    return { id: b.id, x1: a[0], y1: a[1], x2: c[0], y2: c[1], color: off ? '#d03b3b' : kvColor[b.kv] ?? '#999', w: off ? 3 : kvWidth[b.kv] ?? 0.6, off }
  })
  const pts = topo.value.nodes.filter((n) => ids.has(n.id) && pos[n.id]).map((n) => { const a = P(pos[n.id]); return { id: n.id, x: a[0], y: a[1], r: n.kv >= 500 ? 4.5 : n.kv >= 220 ? 3.5 : n.kv >= 110 ? 2.2 : 1.3, color: kvColor[n.kv] ?? '#888' } })
  return { W, H, paths, lines, pts }
})
let ro: ResizeObserver | null = null

const kvColor: Record<number, string> = { 500: '#c0392b', 220: '#e67e22', 110: '#1f5fc4', 35: '#2a9d4a', 10: '#8e6bbf', 6: '#8a8d91' }
const kvWidth: Record<number, number> = { 500: 2.6, 220: 1.8, 110: 1.1, 35: 0.7, 10: 0.5, 6: 0.5 }

const opened = computed(() => {
  const s = new Set<string>(props.outageRows ?? [])
  const bs = props.result?.branch_status ?? {}
  Object.entries(bs).forEach(([l, a]) => { if (a.some((x) => x === 0)) s.add(l) })
  return s
})

function draw() {
  if (!el.value || !topo.value || !geo.value || !geojson.value) return
  if (useSvg.value) { loaded.value = true; return }
  if (!sized()) return          // 容器还没有尺寸（隐藏的标签页等），尺寸出现时再画
  try { drawEcharts() } catch (e) { console.error('ECharts 地图失败，改用 SVG：', e); useSvg.value = true; loaded.value = true }
}
function drawEcharts() {
  if (!el.value || !topo.value || !geo.value || !geojson.value) return
  if (!chart.value) {
    echarts.registerMap('dali', geojson.value)
    chart.value = echarts.init(el.value)
    chart.value.on('click', (p: any) => {
      if (p.seriesName === '站点') detail.value = { kind: 'bus', ...topo.value!.nodes.find((n) => n.id === p.data.id)!, county: geo.value!.county[p.data.id] }
      else if (p.seriesName === '线路' || p.seriesName === '停运/开断') detail.value = { kind: 'branch', ...p.data.br, off: opened.value.has(p.data.br.id) }
    })
  }
  const pos = geo.value.pos
  const sel = new Set(kvSel.value)
  const nodes = topo.value.nodes.filter((n) => sel.has(n.kv) || (showLow.value && n.kv < 110))
  const nodeIds = new Set(nodes.map((n) => n.id))
  const lines = topo.value.branches.filter((b) => (sel.has(b.kv) || (showLow.value && b.kv < 110)) && nodeIds.has(b.from) && nodeIds.has(b.to))
  const normal = lines.filter((b) => !opened.value.has(b.id) && b.in_service).map((b) => ({
    br: b, coords: [pos[b.from], pos[b.to]],
    lineStyle: { color: kvColor[b.kv] ?? '#999', width: kvWidth[b.kv] ?? 0.6, opacity: 0.72 },
  }))
  const off = lines.filter((b) => opened.value.has(b.id) || !b.in_service).map((b) => ({
    br: b, coords: [pos[b.from], pos[b.to]],
    lineStyle: { color: '#d03b3b', width: 3, type: 'dashed', opacity: 1 },
  }))
  const heat = (c: string) => geo.value!.county_counts[c] ?? 0
  chart.value.setOption({
    animation: false,
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        if (p.seriesName === '站点') return `${p.data.id}　${p.data.kv}kV<br/>${geo.value!.county[p.data.id]}`
        if (p.seriesName === '线路' || p.seriesName === '停运/开断') {
          const b = p.data.br
          return `${b.id}（${b.from.slice(1)}–${b.to.slice(1)}，${b.kv}kV）<br/>${opened.value.has(b.id) ? '<b style="color:#d03b3b">停运 / 开断</b>' : (b.load_ratio === null ? '负载率 不限' : '负载率 ' + (b.load_ratio * 100).toFixed(1) + '%')}`
        }
        return p.name ? `${p.name}<br/>节点 ${heat(p.name)} 个` : ''
      },
    },
    geo: {
      map: 'dali', roam: true, aspectScale: 0.95, zoom: 1.05, layoutCenter: ['50%', '52%'], layoutSize: '98%',
      itemStyle: { areaColor: '#eaf1fb', borderColor: '#7f9fcf', borderWidth: 1 },
      emphasis: { itemStyle: { areaColor: '#d5e4fa' }, label: { show: true, color: '#17407c' } },
      label: { show: true, color: '#5b7399', fontSize: 11 },
      select: { disabled: true },
      regions: geojson.value.features.map((f: any) => ({ name: f.properties.name, itemStyle: { areaColor: heat(f.properties.name) > 120 ? '#dde9fa' : '#eaf1fb' } })),
    },
    series: [
      { name: '线路', type: 'lines', coordinateSystem: 'geo', polyline: false, z: 2, silent: false, data: normal },
      { name: '停运/开断', type: 'lines', coordinateSystem: 'geo', polyline: false, z: 4, data: off,
        effect: { show: off.length > 0, period: 4, trailLength: 0.2, symbol: 'circle', symbolSize: 3, color: '#d03b3b' } },
      {
        name: '站点', type: 'scatter', coordinateSystem: 'geo', z: 5,
        symbolSize: (v: any) => (v[2] >= 500 ? 9 : v[2] >= 220 ? 7 : v[2] >= 110 ? 4.5 : 2.5),
        data: nodes.map((n) => ({ id: n.id, kv: n.kv, value: [...pos[n.id], n.kv], itemStyle: { color: kvColor[n.kv] ?? '#888', borderColor: '#fff', borderWidth: n.kv >= 220 ? 1 : 0 } })),
      },
    ],
  }, true)
  loaded.value = true
}

async function load() {
  loadError.value = ''
  loaded.value = false
  try {
    const [t, g, gj] = await Promise.all([api.get<Topo>('/topology'), api.get<any>('/geo'), api.get<any>('/geo/boundary')])
    topo.value = t; geo.value = g; geojson.value = gj
    await nextTick()
    draw()
  } catch (e: any) {
    loadError.value = e?.message || '加载失败'
  }
}
onMounted(() => {
  void load()
  window.addEventListener('resize', rs)
  if (el.value && 'ResizeObserver' in window) {
    ro = new ResizeObserver(() => rs())
    ro.observe(el.value)
  }
})
function sized() { return !!el.value && el.value.clientWidth >= 10 && el.value.clientHeight >= 10 }
function rs() {
  if (!sized()) return                     // 容器被隐藏 / 尺寸为 0（标签页切换、窗口缩放瞬间）：不画也不 resize，避免 canvas 宽高为 0 时重绘报错
  if (chart.value) chart.value.resize(); else draw()
}
onBeforeUnmount(() => {
  window.removeEventListener('resize', rs)
  ro?.disconnect()
  const c = chart.value
  chart.value = null
  if (c) {                                  // 先清空再销毁，避免动画帧在容器已被移除时继续重绘
    try { c.clear() } catch { /* ignore */ }
    c.dispose()
  }
})
watch([kvSel, showLow, () => props.result, () => props.outageRows], draw, { deep: true })

function locate() {
  const q = search.value.trim().toUpperCase()
  if (!q || !topo.value) return
  const n = topo.value.nodes.find((x) => x.id === q)
  const b = topo.value.branches.find((x) => x.id === q)
  if (n) {
    if (!kvSel.value.includes(n.kv)) kvSel.value = [...kvSel.value, n.kv]
    detail.value = { kind: 'bus', ...n, county: geo.value?.county[n.id] }
    chart.value?.dispatchAction({ type: 'geoRoam', zoom: 1 })
  } else if (b) {
    if (!kvSel.value.includes(b.kv)) kvSel.value = [...kvSel.value, b.kv]
    detail.value = { kind: 'branch', ...b, off: opened.value.has(b.id) }
  } else detail.value = { kind: 'none', q }
}
const counties = computed(() => Object.entries(geo.value?.county_counts ?? {}).sort((a, b) => b[1] - a[1]))
defineExpose({ draw })
</script>

<template>
  <div class="dm" data-testid="dali-map">
    <div class="bar">
      <span class="sub">电压等级</span>
      <el-checkbox-group v-model="kvSel" size="small" data-testid="kv-filter">
        <el-checkbox-button v-for="k in [500, 220, 110]" :key="k" :value="k">{{ k }}kV</el-checkbox-button>
      </el-checkbox-group>
      <el-switch v-model="showLow" size="small" active-text="含 35kV 及以下" data-testid="low-switch" />
      <el-switch v-model="useSvg" size="small" active-text="简易绘制" inactive-text="" data-testid="svg-switch" @change="() => nextTick(draw)" />
      <el-input v-model="search" size="small" placeholder="搜索 B43 / L155" style="width: 170px" data-testid="map-search" @keyup.enter="locate" />
      <el-button size="small" @click="locate">定位</el-button>
      <span class="grow" />
      <span class="lg"><i v-for="(c, k) in kvColor" :key="k" :style="{ background: c }" />{{ Object.keys(kvColor).join(' / ') }} kV</span>
      <span class="lg off"><i /> 停运 / 开断</span>
    </div>
    <div class="wrap" :style="{ height: (height ?? 620) + 'px' }">
      <div v-show="!useSvg" ref="el" class="cv" data-testid="map-canvas" />
      <svg v-if="useSvg && svgData" class="cv svgmap" :viewBox="`0 0 ${svgData.W} ${svgData.H}`" preserveAspectRatio="xMidYMid meet" data-testid="map-svg">
        <path v-for="c in svgData.paths" :key="c.name" :d="c.d" fill="#eaf1fb" stroke="#7f9fcf" stroke-width="1.2" />
        <text v-for="c in svgData.paths" :key="'t' + c.name" :x="c.lx" :y="c.ly" font-size="13" fill="#5b7399" text-anchor="middle">{{ c.name.replace('彝族自治县', '').replace('彝族回族自治县', '') }}</text>
        <line v-for="l in svgData.lines" :key="l.id" :x1="l.x1" :y1="l.y1" :x2="l.x2" :y2="l.y2" :stroke="l.color" :stroke-width="l.w" :stroke-dasharray="l.off ? '6 4' : undefined" opacity="0.8" @click="detail = { kind: 'branch', ...topo!.branches.find((b) => b.id === l.id)!, off: l.off }" />
        <circle v-for="n in svgData.pts" :key="n.id" :cx="n.x" :cy="n.y" :r="n.r" :fill="n.color" stroke="#fff" stroke-width="0.6" @click="detail = { kind: 'bus', ...topo!.nodes.find((b) => b.id === n.id)!, county: geo!.county[n.id] }" />
      </svg>
      <div v-if="loadError" class="loading err">地图数据加载失败：{{ loadError }}<el-button size="small" type="primary" style="margin-left: 10px" data-testid="map-retry" @click="load">重试</el-button></div>
      <div v-else-if="!loaded" class="loading">正在载入行政区划与网架…</div>
      <div class="counties card">
        <b>各县（市）节点数</b>
        <div v-for="[n, c] in counties" :key="n" class="cr"><span>{{ n.replace('彝族自治县', '').replace('彝族回族自治县', '') }}</span><i :style="{ width: Math.max(4, c / 1.5) + 'px' }" /><em>{{ c }}</em></div>
      </div>
      <div v-if="detail" class="detail card" data-testid="map-detail">
        <el-button size="small" text class="x" @click="detail = null">×</el-button>
        <template v-if="detail.kind === 'bus'">
          <b>{{ detail.id }}</b> <span class="sub">{{ detail.kv }}kV</span>
          <div class="sub">{{ detail.county }}</div>
          <div>PD {{ detail.pd }} MW · VM {{ detail.vm }}</div>
        </template>
        <template v-else-if="detail.kind === 'branch'">
          <b>{{ detail.id }}</b>（{{ detail.from.slice(1) }}–{{ detail.to.slice(1) }}，{{ detail.kv }}kV）
          <div class="sub">{{ detail.transformer ? '变压器支路' : '线路' }} · {{ detail.isolating ? '孤岛型' : '网状部分' }}</div>
          <div :class="detail.off ? 'lv-error' : ''">{{ detail.off ? '停运 / 开断' : '在运' }} · RATE_A {{ detail.rate_a || '不限' }} · 负载率 {{ detail.load_ratio == null ? '不限' : (detail.load_ratio * 100).toFixed(1) + '%' }}</div>
        </template>
        <div v-else class="lv-warn">没有找到 {{ detail.q }}</div>
      </div>
    </div>
    <p class="sub note">底图为大理白族自治州真实行政区划；站点落在各县范围内，是按拓扑分区的示意位置，不是真实站址。</p>
  </div>
</template>

<style scoped>
.bar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 10px; }
.wrap { position: relative; border-radius: 12px; overflow: hidden; border: 1px solid var(--c-hairline); background: linear-gradient(180deg, #f7faff, #eef4fc); }
.cv { position: absolute; inset: 0; } .svgmap { width: 100%; height: 100%; }
.loading { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--c-muted); z-index: 3; background: rgba(247, 250, 255, 0.85); } .loading.err { color: var(--c-danger); }
.counties { position: absolute; left: 12px; bottom: 12px; padding: 10px 12px; font-size: 11.5px; background: rgba(255, 255, 255, 0.92); max-height: 60%; overflow: auto; }
.cr { display: flex; align-items: center; gap: 6px; margin-top: 3px; } .cr span { width: 52px; color: var(--c-muted); } .cr i { height: 6px; background: var(--c-primary); border-radius: 3px; opacity: 0.6; } .cr em { font-style: normal; color: var(--c-muted); }
.detail { position: absolute; right: 12px; top: 12px; width: 290px; padding: 12px 14px; font-size: 13px; background: rgba(255, 255, 255, 0.96); }
.x { position: absolute; right: 2px; top: 2px; }
.lg { font-size: 11.5px; color: var(--c-muted); display: inline-flex; align-items: center; gap: 3px; }
.lg i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 2px; }
.lg.off i { border-radius: 0; height: 0; width: 18px; border-top: 3px dashed #d03b3b; background: none; }
.note { margin-top: 6px; }
</style>
