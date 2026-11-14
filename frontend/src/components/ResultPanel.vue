<script setup lang="ts">
// 结果与地图：顶部摘要；开断方案（单时段是清单，多时段是矩阵）、机组出力调整（前后对比表，多时段加曲线）、大理地图、回写测点。
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '@/api/client'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'
import DaliMap from '@/components/DaliMap.vue'
import type { SolveResult } from '@/types/later'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])
const t = useTaskStore()
const result = ref<SolveResult | null>(null)
const tab = ref('plan')
const showAll = ref(false)
const genEl = ref<HTMLElement | null>(null)
let genChart: echarts.ECharts | null = null
const base = ref<{ gen: Record<string, number>; branch: Record<string, any> }>({ gen: {}, branch: {} })
const wb = ref<any>(null)
const v = computed(() => t.viewVersion ?? t.current)
const ready = ref(false)
const hasPlan = computed(() => !!result.value && ['optimal', 'feasible'].includes(result.value.status))
const nPer = computed(() => result.value?.periods ?? 1)
const outageRows = computed(() => (t.spec?.delta_pi ?? []).filter((d) => d.param === 'BR_STATUS' && d.value === 0).map((d) => d.target))

onMounted(load)
watch(() => [t.viewVersion, t.current, t.resultTick], load)
async function load() {
  if (!t.taskId || v.value === null) return
  ready.value = false
  const res = (await api.get<{ result: SolveResult | null }>(`/tasks/${t.taskId}/results?version=${v.value}`)).result
  if (res && ['optimal', 'feasible'].includes(res.status)) {
    const [topo, gb, w] = await Promise.all([api.get<any>('/topology'), api.get<any>('/gen-base'), api.get<any>(`/tasks/${t.taskId}/writeback?version=${v.value}`)])
    base.value.branch = Object.fromEntries(topo.branches.map((b: any) => [b.id, b]))
    base.value.gen = gb.pg
    wb.value = w
  }
  result.value = res          // 基础数据就绪后再放出结果，避免先渲染出空端点
  ready.value = true
}

const statusText = computed(() => ({ optimal: '最优', feasible: '可行', infeasible: '无可行方案', error: '出错', mock: '占位' } as Record<string, string>)[result.value?.status ?? ''] ?? '—')

// ---- 开断方案
const planRows = computed(() => {
  const r = result.value
  if (!r?.branch_status) return []
  return Object.entries(r.branch_status)
    .map(([id, a]) => ({ id, v: a, off: a.map((x, i) => (x === 0 ? i + 1 : 0)).filter(Boolean), b: base.value.branch[id] }))
    .filter((x) => showAll.value || x.off.length)
})
const maintenance = computed(() => new Set(outageRows.value))

// ---- 机组调整
const genRows = computed(() => {
  const g = result.value?.gen_p ?? {}
  return Object.entries(g).map(([id, a]) => {
    const b = base.value.gen[id] ?? 0
    return { id, before: b, after: a[0], delta: a[0] - b, series: a }
  }).sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta))
})
const totalDelta = computed(() => genRows.value.reduce((s, r) => s + r.delta, 0))
async function drawGen() {
  await nextTick()
  if (!genEl.value || nPer.value < 2) return
  genChart?.dispose()
  genChart = echarts.init(genEl.value)
  genChart.setOption({
    animation: false, tooltip: { trigger: 'axis' }, legend: { type: 'scroll', top: 0 }, grid: { left: 50, right: 20, top: 36, bottom: 30 },
    xAxis: { type: 'category', data: Array.from({ length: nPer.value }, (_, i) => `${i + 1}`), name: '时段' }, yAxis: { type: 'value', name: 'MW' },
    series: genRows.value.slice(0, 10).map((r) => ({ name: r.id, type: 'line', data: r.series, symbolSize: 5 })),
  })
}
watch([tab, genRows], () => { if (tab.value === 'gen') void drawGen() })

// ---- 潮流变化
const flowRows = computed(() => {
  const f = result.value?.branch_flow ?? {}
  const out: any[] = []
  for (const [id, d] of Object.entries(f)) {
    const b = base.value.branch[id]
    if (!b || !d.pf?.length) continue
    const after = d.pf[0]
    if (Math.abs(after - b.pf) > 5 && b.rate_a > 0) out.push({ id, label: `${b.from.slice(1)}–${b.to.slice(1)}（${b.kv}kV）`, before: b.pf, after, rate: b.rate_a, rho: Math.abs(after) / b.rate_a })
  }
  return out.sort((x, y) => Math.abs(y.after - y.before) - Math.abs(x.after - x.before)).slice(0, 12)
})
const f1 = (x: number) => (x >= 0 ? '+' : '') + x.toFixed(1)
</script>

<template>
  <div class="rp" data-testid="result-panel">
    <div v-if="!ready" class="empty big">载入结果…</div>
    <div v-else-if="!hasPlan" class="empty big" data-testid="no-plan">
      {{ result?.status === 'infeasible' ? '没有找到可行方案：限额过紧或约束互相冲突。回到规格确认调整后再求解。' : result?.status === 'mock' ? '当前是占位模式，没有方案。' : '还没有求解结果。' }}
    </div>

    <template v-else>
      <div class="strip" data-testid="result-strip">
        <div class="s"><span>求解状态</span><b class="ok">{{ statusText }}</b></div>
        <div class="s"><span>开断支路</span><b data-testid="n-open">{{ planRows.filter((r) => r.off.length).length }}</b></div>
        <div class="s"><span>调整机组</span><b>{{ genRows.length }}</b></div>
        <div class="s"><span>出力调整合计</span><b>{{ f1(totalDelta) }} MW</b></div>
        <div class="s"><span>求解耗时</span><b>{{ result?.timings_s?.solve != null ? result.timings_s.solve.toFixed(2) + ' s' : '—' }}</b></div>
        <div class="s"><span>求解器</span><b class="sm">{{ result?.solver }}</b></div>
      </div>

      <el-tabs v-model="tab" data-testid="result-tabs">
        <el-tab-pane label="开断方案" name="plan">
          <div v-if="nPer > 1" class="row" style="margin-bottom: 8px"><el-switch v-model="showAll" active-text="显示全部可开断支路" size="small" /></div>
          <div v-if="!planRows.length" class="empty" data-testid="matrix-empty">本方案没有开断动作：保持现有网架。</div>
          <table v-else-if="nPer === 1" class="table-plain" data-testid="switch-list">
            <thead><tr><th>支路</th><th>端点 / 电压</th><th>动作</th><th>原因</th><th>断面潮流</th></tr></thead>
            <tbody>
              <tr v-for="r in planRows" :key="r.id" :data-open="r.id">
                <td class="mono"><b>{{ r.id }}</b></td>
                <td>{{ r.b ? `${r.b.from.slice(1)}–${r.b.to.slice(1)}，${r.b.kv}kV` : '—' }}</td>
                <td><span class="tag-off">断开</span></td>
                <td>{{ maintenance.has(r.id) ? '检修停运（指令）' : '求解器优化选择：让潮流满足限额与 N−1' }}</td>
                <td>{{ r.b ? r.b.pf.toFixed(1) + ' MW' : '—' }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="mx" data-testid="switch-matrix">
            <table>
              <thead><tr><th>支路</th><th v-for="i in nPer" :key="i">{{ i }}</th></tr></thead>
              <tbody><tr v-for="r in planRows" :key="r.id"><th>{{ r.id }}</th><td v-for="(x, i) in r.v" :key="i" :class="{ off: x === 0 }" :data-off="x === 0" /></tr></tbody>
            </table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="机组出力调整" name="gen" lazy>
          <div v-if="!genRows.length" class="empty" data-testid="gen-empty">机组出力没有变化。</div>
          <template v-else>
            <table class="table-plain" data-testid="gen-table">
              <thead><tr><th>机组</th><th>调整前 MW</th><th>调整后 MW</th><th>变化 MW</th></tr></thead>
              <tbody>
                <tr v-for="r in genRows.slice(0, 12)" :key="r.id"><td class="mono"><b>{{ r.id }}</b></td><td>{{ r.before.toFixed(2) }}</td><td>{{ r.after.toFixed(2) }}</td>
                  <td :class="r.delta >= 0 ? 'up' : 'down'"><b>{{ f1(r.delta) }}</b></td></tr>
              </tbody>
            </table>
            <p v-if="genRows.length > 12" class="sub">仅列变化最大的 12 台，共 {{ genRows.length }} 台。</p>
            <div v-if="nPer > 1" ref="genEl" class="gchart" data-testid="gen-chart" />
          </template>
        </el-tab-pane>

        <el-tab-pane label="电网地图" name="map" lazy><DaliMap :result="result" :outage-rows="outageRows" :height="560" /></el-tab-pane>

        <el-tab-pane label="潮流变化" name="flow">
          <div v-if="!flowRows.length" class="empty" data-testid="compare-empty">没有明显变化的支路潮流。</div>
          <table v-else class="table-plain" data-testid="compare-table">
            <thead><tr><th>支路</th><th>端点</th><th>调整前 MW</th><th>调整后 MW</th><th>调整后负载率</th></tr></thead>
            <tbody><tr v-for="r in flowRows" :key="r.id"><td class="mono"><b>{{ r.id }}</b></td><td>{{ r.label }}</td><td>{{ r.before.toFixed(1) }}</td><td>{{ r.after.toFixed(1) }}</td>
              <td :class="{ 'lv-error': r.rho >= 1, 'lv-warn': r.rho >= 0.8 && r.rho < 1 }">{{ (r.rho * 100).toFixed(1) }}%</td></tr></tbody>
          </table>
        </el-tab-pane>

        <el-tab-pane name="writeback"><template #label>回写测点 <StatusBadge feature="m6.writeback" small /></template>
          <p class="sub">把开断方案映射成虚拟开关动作清单（课题 2 测点）。</p>
          <table v-if="wb?.actions?.length" class="table-plain" data-testid="wb-table">
            <thead><tr><th>开关</th><th>支路</th><th>动作</th></tr></thead>
            <tbody><tr v-for="(a, i) in wb.actions" :key="i"><td class="mono">{{ a.switch }}</td><td>{{ a.branch }}</td><td :class="a.action === '断开' ? 'lv-error' : 'lv-info'"><b>{{ a.action }}</b></td></tr></tbody>
          </table>
          <div v-else class="empty">没有开关动作。</div>
          <p v-if="wb?.note" class="sub">{{ wb.note }}</p>
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<style scoped>
.strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 14px; }
.s { background: var(--c-surface); border: 1px solid var(--c-hairline); border-radius: 12px; padding: 12px 16px; display: flex; flex-direction: column; box-shadow: var(--shadow); }
.s span { font-size: 12px; color: var(--c-muted); } .s b { font-size: 24px; color: var(--c-brand-blue); } .s b.ok { color: var(--c-success); } .s b.sm { font-size: 14px; line-height: 2; }
.empty { padding: 20px; border: 1px dashed var(--c-border); border-radius: var(--radius); color: var(--c-muted); } .empty.big { padding: 40px; text-align: center; }
.tag-off { background: var(--c-danger-bg); color: var(--c-danger); font-weight: 600; padding: 1px 10px; border-radius: 10px; }
.up { color: #d03b3b; } .down { color: #2a9d4a; }
.mx { overflow: auto; max-height: 460px; } .mx table { border-collapse: collapse; font-size: 11px; }
.mx th { padding: 2px 6px; background: var(--c-surface-2); font-family: var(--font-mono); } .mx td { width: 22px; height: 20px; border: 1px solid var(--c-hairline); background: var(--c-success-bg); } .mx td.off { background: var(--c-danger); }
.gchart { height: 340px; margin-top: 12px; }
</style>
