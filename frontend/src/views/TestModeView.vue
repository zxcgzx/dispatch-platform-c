<script setup lang="ts">
// 测评模式（M8）：导入测试集（JSON / CSV）、选引擎、批量跑“解析 → 判级 → 校验”（默认不求解）；
// 结果用表格和按层级的柱状图展示；每条用例可点开回放；可导出 Markdown / CSV。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '@/api/client'
import StatusBadge from '@/components/StatusBadge.vue'
import type { EngineOption } from '@/types/api'

echarts.use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])
const sets = ref<{ id: string; name: string; cases: number; builtin: boolean }[]>([])
const setId = ref('builtin')
const engines = ref<EngineOption[]>([])
const engine = ref('demo')
const skipTrial = ref(true)
const running = ref(false)
const run = ref<any>(null)
const open = ref<any>(null)
const chartEl = ref<HTMLElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)

onMounted(async () => {
  sets.value = (await api.get<any>('/testsets')).testsets
  engines.value = (await api.get<any>('/meta')).engines
})
onBeforeUnmount(() => chart.value?.dispose())
const rep = computed(() => run.value?.report)
const pct = (x: number | null | undefined) => (x === null || x === undefined ? '—' : (x * 100).toFixed(1) + '%')

async function upload(ev: Event) {
  const f = (ev.target as HTMLInputElement).files?.[0]
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  try {
    const r = await api.upload<any>('/testsets', fd)
    sets.value = (await api.get<any>('/testsets')).testsets
    setId.value = r.id
    ElMessage.success(`已导入 ${r.name}（${r.cases} 条）`)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
  ;(ev.target as HTMLInputElement).value = ''
}
async function go() {
  running.value = true
  try {
    run.value = await api.post(`/testsets/${setId.value}/run`, { engine: engine.value, skip_trial: skipTrial.value })
    await nextTick()
    draw()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    running.value = false
  }
}
function draw() {
  if (!chartEl.value || !rep.value) return
  chart.value ??= echarts.init(chartEl.value)
  const lv = Object.keys(rep.value.by_level)
  chart.value.setOption({
    animation: false, tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 40, right: 20, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: lv }, yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    series: [
      { name: '层级准确率', type: 'bar', data: lv.map((k) => +(rep.value.by_level[k].level_acc * 100).toFixed(1)), itemStyle: { color: '#2f6fde' } },
      { name: '规格级准确率', type: 'bar', data: lv.map((k) => +(rep.value.by_level[k].acc * 100).toFixed(1)), itemStyle: { color: '#2a9d4a' } },
    ],
  }, true)
}
watch(run, async () => { await nextTick(); draw() })
function dl(kind: 'md' | 'csv') {
  window.open(`/api/testsets/${setId.value}/report.${kind}?run=${run.value.id}`, '_blank')
}
const statusText = (x: any) => (x.error ? '出错' : x.ok ? '通过' : '未通过')
</script>

<template>
  <div class="page">
    <h2>测评模式 <StatusBadge feature="m8.testmode" /></h2>
    <p class="sub">批量跑“解析 → 判级 → 校验”，默认不求解。比对是<b>规格级</b>：层级一致；Δπ 按 target / param / 操作或方向 / 数值（相对误差 ≤ 1%）/ 时段匹配；s 按算子与参数匹配；标了 must_fail 的用例，M4 要报出对应错误才算对。目标值比对 <StatusBadge feature="m8.objective" small />（等求解接入后再做）。</p>
    <section class="card card-pad ctl">
      <div class="row" style="flex-wrap: wrap; gap: 14px">
        <label class="f"><span>测试集</span>
          <el-select v-model="setId" size="small" style="width: 260px" data-testid="set-select"><el-option v-for="s in sets" :key="s.id" :value="s.id" :label="`${s.name}（${s.cases} 条）`" /></el-select></label>
        <label class="f"><span>导入测试集（JSON / CSV）</span><input type="file" accept=".json,.csv" data-testid="set-upload" @change="upload" /></label>
        <label class="f"><span>引擎</span>
          <el-select v-model="engine" size="small" style="width: 220px" data-testid="tm-engine"><el-option v-for="e in engines" :key="e.id" :value="e.id" :label="e.label" :disabled="!e.selectable" /></el-select></label>
        <label class="f"><span>试构建（慢）</span><el-switch v-model="skipTrial" inactive-text="跑" active-text="跳过" size="small" /></label>
        <el-button type="primary" :loading="running" data-testid="run-set" @click="go">运行测评</el-button>
      </div>
      <p class="sub" style="margin-top: 6px">CSV 列：id, instruction, expected_level, expected_json（{"delta_pi":[…],"structural":[…]}）, must_fail（用 ; 分隔）。</p>
    </section>

    <template v-if="rep">
      <section class="cards" data-testid="report-cards">
        <div class="card card-pad kpi"><span class="sub">规格级通过</span><b data-testid="kpi-pass">{{ rep.passed }}/{{ rep.total }}</b><span class="sub">{{ pct(rep.accuracy) }}</span></div>
        <div class="card card-pad kpi"><span class="sub">层级准确率</span><b>{{ pct(rep.level_accuracy) }}</b></div>
        <div class="card card-pad kpi"><span class="sub">Δπ 精确率 / 召回率</span><b>{{ pct(rep.dp_precision) }} / {{ pct(rep.dp_recall) }}</b><span class="sub">{{ rep.dp_tp }}/{{ rep.dp_got }} · {{ rep.dp_tp }}/{{ rep.dp_expected }}</span></div>
        <div class="card card-pad kpi"><span class="sub">疑似幻觉（W501 + E101）</span><b data-testid="kpi-hall">{{ rep.hallucinations }}</b></div>
        <div class="card card-pad kpi"><span class="sub">平均耗时</span><b>{{ rep.avg_ms.toFixed(0) }} ms</b></div>
      </section>
      <div class="row" style="margin: 8px 0"><el-button size="small" data-testid="export-md" @click="dl('md')">导出 Markdown</el-button><el-button size="small" data-testid="export-csv" @click="dl('csv')">导出 CSV</el-button></div>
      <section class="card card-pad">
        <div class="card-title">按层级统计</div>
        <div class="two">
          <table class="table-plain" data-testid="level-table">
            <thead><tr><th>层级</th><th>用例数</th><th>层级正确</th><th>规格级通过</th><th>准确率</th></tr></thead>
            <tbody><tr v-for="(d, k) in rep.by_level" :key="k"><td>{{ k }}</td><td>{{ d.total }}</td><td>{{ d.level_ok }}</td><td>{{ d.ok }}</td><td>{{ pct(d.acc) }}</td></tr></tbody>
          </table>
          <div ref="chartEl" class="chart" data-testid="level-chart" />
        </div>
      </section>
      <section class="card card-pad" style="margin-top: 12px">
        <div class="card-title">逐条用例 <span class="sub">点一行回放</span></div>
        <table class="table-plain" data-testid="case-table">
          <thead><tr><th>编号</th><th>指令</th><th>期望</th><th>判级</th><th>结果</th><th>错/警</th><th>耗时</th></tr></thead>
          <tbody>
            <tr v-for="x in run.results" :key="x.id" class="clk" :data-case="x.id" @click="open = x">
              <td class="mono">{{ x.id }}</td><td>{{ x.instruction }}</td><td>{{ x.expected_level }}</td><td>{{ x.level ?? '—' }}</td>
              <td :class="x.ok ? 'lv-info' : 'lv-error'"><b>{{ statusText(x) }}</b></td>
              <td>{{ x.check_counts ? `${x.check_counts.error}/${x.check_counts.warn}` : '—' }}</td><td>{{ x.elapsed_ms }} ms</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <el-drawer :model-value="!!open" title="用例回放" size="640px" append-to-body @close="open = null">
      <div v-if="open" data-testid="replay">
        <p><b>{{ open.id }}</b> · {{ open.instruction }}</p>
        <p class="sub">期望 {{ open.expected_level }} · 判级 {{ open.level }} · {{ statusText(open) }}（{{ open.engine }}）<span v-if="open.fallback" class="lv-warn"> · {{ open.fallback }}</span></p>
        <p v-if="open.error" class="lv-error">{{ open.error }}</p>
        <h4>规格</h4>
        <table class="table-plain"><thead><tr><th>编号</th><th>对象.参数</th><th>操作</th><th>数值</th><th>时段</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-for="d in open.spec?.delta_pi" :key="d.id" :class="{ 'infer-row': d.source === 'inferred' }"><td>{{ d.id }}</td><td>{{ d.target }}.{{ d.param }}</td><td>{{ d.operation ?? d.direction }}</td><td>{{ d.value ?? '待确认' }}</td><td>{{ d.periods.length ? d.periods.join(',') : '全部' }}</td><td>{{ d.source === 'inferred' ? '推断' : '明确' }}</td></tr>
            <tr v-for="s in open.spec?.structural" :key="s.id"><td>{{ s.id }}</td><td colspan="5">{{ s.op_id }} {{ JSON.stringify(s.params) }}</td></tr>
          </tbody></table>
        <h4>比对</h4>
        <ul class="sub">
          <li>层级：{{ open.level_ok ? '一致' : '不一致' }}</li>
          <li>Δπ：期望 {{ open.dp.expected }} 条，命中 {{ open.dp.tp }}，缺 {{ open.dp.missing?.length ?? 0 }}，多 {{ open.dp.extra?.length ?? 0 }}</li>
          <li v-if="open.s">s：期望 {{ open.s.expected }}，缺 {{ open.s.missing.length }}，多 {{ open.s.extra.length }}</li>
          <li v-if="open.must_fail_ok === false" class="lv-error">must_fail 没有报出对应错误</li>
        </ul>
        <h4>校验发现</h4>
        <div v-for="(f, i) in open.findings" :key="i" class="sub"><b :class="'lv-' + f.level">{{ f.code }}</b> {{ f.message }}</div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.ctl { margin-bottom: 12px; }
.f { display: flex; flex-direction: column; gap: 3px; font-size: var(--fs-xs); color: var(--c-muted); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: var(--sp-3); }
.kpi { display: flex; flex-direction: column; gap: 2px; } .kpi b { font-size: 24px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-4); align-items: start; }
.chart { height: 240px; }
.clk { cursor: pointer; } .clk:hover { background: var(--c-primary-bg); }
</style>
