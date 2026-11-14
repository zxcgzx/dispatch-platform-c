<script setup lang="ts">
// 905 节点 16 时段完整交流 OTS 基准（MATLAB 计算结果，只读展示）：结论、逐时段指标、热启动对比、报告原文。
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'

const d = ref<any>(null)
const err = ref('')
const tab = ref('periods')
onMounted(async () => {
  try { d.value = await api.get('/benchmark/ots905') } catch (e: any) { err.value = e?.message || '加载失败' }
})

const gain = computed(() => (d.value ? d.value.summary.obj_noopen_4h - d.value.summary.obj_4h : 0))
// 逐时段目标值曲线（纯 SVG）：开断方案 vs 不开断
const chart = computed(() => {
  const P = d.value?.periods ?? []
  if (!P.length) return null
  const W = 640, H = 220, L = 46, R = 12, T = 14, B = 28
  const all = P.flatMap((p: any) => [p.J_AC, p.J_AC_no_opening])
  const lo = Math.min(...all) - 1, hi = Math.max(...all) + 1
  const x = (i: number) => L + (i * (W - L - R)) / (P.length - 1)
  const y = (v: number) => T + ((hi - v) * (H - T - B)) / (hi - lo)
  const line = (k: string) => P.map((p: any, i: number) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`).join('')
  const ticks = [lo, (lo + hi) / 2, hi].map((v) => ({ v: v.toFixed(0), y: y(v) }))
  return { W, H, a: line('J_AC'), b: line('J_AC_no_opening'), ticks, xs: P.map((_: any, i: number) => ({ i: i + 1, x: x(i) })).filter((_: any, i: number) => i % 3 === 0), L, B }
})
const f = (v: any, n = 2) => (typeof v === 'number' ? v.toFixed(n) : v)
</script>

<template>
  <div class="page">
    <div class="head">
      <div>
        <h2>905 节点 · 16 时段交流 OTS 基准</h2>
        <p class="sub">MATLAB + MATPOWER 8（MIPS）完整非线性交流 OPF 的计算结果，只读展示；与平台内置的直流求解互为对照。</p>
      </div>
    </div>
    <div v-if="err" class="card card-pad lv-error">{{ err }}</div>
    <template v-else-if="d">
      <div class="kpis" data-testid="bench-kpis">
        <div class="k"><b>{{ d.opened.join('、') }}</b><span>全程开断的支路</span></div>
        <div class="k"><b>{{ f(d.summary.obj_4h) }}</b><span>4 小时交流目标 $（不开断 {{ f(d.summary.obj_noopen_4h) }}，降 {{ f(gain) }}）</span></div>
        <div class="k"><b>{{ d.summary.ac_opf_runs }} / {{ d.summary.n1_runs }}</b><span>完整交流 OPF 次数 / 静态 N−1 次数</span></div>
        <div class="k"><b>{{ f(d.summary.total_s, 0) }} s</b><span>基准总用时（约 {{ f(d.summary.total_s / 60, 1) }} 分钟）</span></div>
      </div>
      <el-tabs v-model="tab" class="card card-pad">
        <el-tab-pane label="逐时段结果" name="periods">
          <svg v-if="chart" class="ch" :viewBox="`0 0 ${chart.W} ${chart.H}`" data-testid="bench-chart">
            <line v-for="t in chart.ticks" :key="t.v" :x1="chart.L" :x2="chart.W - 12" :y1="t.y" :y2="t.y" stroke="#e3e6eb" />
            <text v-for="t in chart.ticks" :key="'l' + t.v" :x="chart.L - 6" :y="t.y + 4" text-anchor="end" font-size="11" fill="#6b7280">{{ t.v }}</text>
            <text v-for="x in chart.xs" :key="x.i" :x="x.x" :y="chart.H - 8" text-anchor="middle" font-size="11" fill="#6b7280">{{ x.i }}</text>
            <path :d="chart.b" fill="none" stroke="#9aa3b2" stroke-width="2" stroke-dasharray="5 4" />
            <path :d="chart.a" fill="none" stroke="#1f5fc4" stroke-width="2.4" />
          </svg>
          <div class="legend"><i style="background:#1f5fc4" />开断方案 J_AC　<i style="background:#9aa3b2" />不开断 J_AC　（$/h，横轴为时段）</div>
          <el-table :data="d.periods" size="small" max-height="420" stripe>
            <el-table-column prop="t" label="时段" width="62" />
            <el-table-column label="负荷系数" width="86"><template #default="{ row }">{{ f(row.load_factor, 3) }}</template></el-table-column>
            <el-table-column label="开断" width="70"><template #default="{ row }">L{{ row.open_row }}</template></el-table-column>
            <el-table-column label="J_AC" width="86"><template #default="{ row }">{{ f(row.J_AC, 3) }}</template></el-table-column>
            <el-table-column label="不开断 J_AC" width="104"><template #default="{ row }">{{ f(row.J_AC_no_opening, 3) }}</template></el-table-column>
            <el-table-column label="网损 MW" width="86"><template #default="{ row }">{{ f(row.loss_MW) }}</template></el-table-column>
            <el-table-column label="电压越限 p.u." width="110"><template #default="{ row }">{{ f(row.viol_pu, 4) }}</template></el-table-column>
            <el-table-column label="N−1 紧急合格率" width="120"><template #default="{ row }">{{ f(row.n1_emergency_pct, 1) }}%</template></el-table-column>
            <el-table-column label="N−1" width="70"><template #default="{ row }">{{ row.n1_status }}</template></el-table-column>
            <el-table-column label="可调出力 MW" width="110"><template #default="{ row }">{{ f(row.disp_pg_MW, 1) }}</template></el-table-column>
            <el-table-column label="VM 范围"><template #default="{ row }">{{ row.vm_min }} – {{ row.vm_max }}</template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="热启动对比" name="speed">
          <el-table :data="d.speed" size="small" data-testid="bench-speed">
            <el-table-column prop="name" label="实验" width="110" />
            <el-table-column prop="init" label="初值来源" />
            <el-table-column prop="usable" label="可作 4.1 用时" width="150" />
            <el-table-column prop="total_s" label="总用时 s" width="90" />
            <el-table-column prop="opf_s" label="OPF s" width="80" />
            <el-table-column prop="n1_s" label="N−1 s" width="80" />
            <el-table-column prop="obj_4h" label="4h 目标 $" width="100" />
            <el-table-column prop="obj_noopen_4h" label="不开断 $" width="100" />
          </el-table>
          <p class="sub">E1 与 E4 是同一算例，E2、E3 的负荷不同，目标值不可直接比较。</p>
        </el-tab-pane>
        <el-tab-pane label="报告原文" name="report"><pre class="rep">{{ d.report_md }}</pre></el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<style scoped>
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 14px; }
.k { background: var(--c-surface); border: 1px solid var(--c-hairline); border-radius: var(--radius); padding: 14px 16px; box-shadow: var(--shadow); }
.k b { display: block; font-size: 22px; color: var(--c-primary-ink); } .k span { font-size: 12px; color: var(--c-muted); }
.ch { width: 100%; max-width: 760px; height: auto; }
.legend { font-size: 12px; color: var(--c-muted); margin: 4px 0 12px; } .legend i { display: inline-block; width: 18px; height: 3px; margin-right: 4px; vertical-align: middle; }
.rep { white-space: pre-wrap; font-size: 12.5px; line-height: 1.7; max-height: 560px; overflow: auto; }
</style>
