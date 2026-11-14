<script setup lang="ts">
// 测点转换（课题 2 接口）：节点 → 模拟测点 的构造、静态 / 动态表、测点 → 节点 的逆向恢复与往返验证、方案回写（开关动作）。
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import StatusBadge from '@/components/StatusBadge.vue'

const sum = ref<any>(null)
const tables = ref<any>(null)
const rt = ref<any>(null)
const tasks = ref<any[]>([])
const tid = ref('')
const wb = ref<any>(null)
const tab = ref('static')
const sub = ref('开关')
const rtBusy = ref(false)

onMounted(async () => {
  sum.value = await api.get('/measure/summary')
  tables.value = await api.get('/measure/tables?limit=12')
  tasks.value = (await api.get<any>('/tasks')).tasks.filter((t: any) => t.version)
})
async function runRoundtrip() {
  rtBusy.value = true
  try { rt.value = await api.get('/measure/roundtrip') } finally { rtBusy.value = false }
}
async function loadWb() {
  wb.value = tid.value ? await api.get(`/tasks/${tid.value}/writeback`) : null
}
const cols = (rows: any[]) => (rows?.length ? Object.keys(rows[0]) : [])
const cur = computed(() => (tab.value === 'static' ? tables.value?.static : tables.value?.dynamic))

const steps = [
  { n: '1', t: '母线 → 母线测点', d: '每个母线节点对应一个母线测点（905 个）。' },
  { n: '2', t: '线路 → 两端虚拟开关', d: '每条支路两端各插入一个虚拟开关；原线路的阻抗、热稳极限放在两个开关之间的线路边，母线—开关两段是零阻抗连接边，只表示连接关系和状态。' },
  { n: '3', t: '变压器 → 变压器测点', d: '变比不为 0 的支路视为变压器，两端同样插入开关，中间是变压器测点（档位 / 变比）。' },
  { n: '4', t: '发电机、负荷 → 边界开关', d: '发电机和负荷不建独立测点，信息挂在边界开关上：有机组的母线挂一个发电机边界开关，有负荷的母线挂一个负荷边界开关。' },
]
</script>

<template>
  <div class="page">
    <h2>测点 ↔ 节点转换 <StatusBadge feature="m1.tp_data" /></h2>
    <p class="sub">课题 2 的测点数据以“母线、变压器、开关、连接线路”四类对象组织。这里按怀柔实验室的构造机制，把节点模型转成<b>模拟测点</b>，并支持逆向恢复和方案回写。真实测点接入需要课题 2 提供映射与字段字典。</p>

    <div v-if="sum" class="kpis" data-testid="measure-kpis">
      <div class="kpi"><span>母线测点</span><b>{{ sum.bus_mp }}</b></div>
      <div class="kpi"><span>线路两端开关</span><b>{{ sum.line_switches }}</b></div>
      <div class="kpi"><span>边界开关</span><b>{{ sum.boundary_switches }}</b><em>发电 {{ sum.boundary_gen }} · 负荷 {{ sum.boundary_load }}</em></div>
      <div class="kpi"><span>变压器测点</span><b>{{ sum.trafos }}</b></div>
      <div class="kpi"><span>连接线路（边）</span><b>{{ sum.links }}</b></div>
      <div class="kpi hl"><span>测点总数</span><b>{{ sum.mp_total.toLocaleString() }}</b></div>
    </div>

    <div class="flow card card-pad">
      <div class="card-title">节点 → 测点：构造步骤</div>
      <div class="steps">
        <div v-for="s in steps" :key="s.n" class="st"><i>{{ s.n }}</i><b>{{ s.t }}</b><span>{{ s.d }}</span></div>
      </div>
    </div>

    <div class="card card-pad" style="margin-top: 12px">
      <div class="card-title">静态表 / 动态表（前 12 行预览）</div>
      <el-radio-group v-model="tab" size="small" data-testid="mtab"><el-radio-button value="static">静态表（拓扑与参数）</el-radio-button><el-radio-button value="dynamic">动态表（量测与状态）</el-radio-button></el-radio-group>
      <el-radio-group v-model="sub" size="small" style="margin-left: 12px" data-testid="msub">
        <el-radio-button v-for="k in ['母线', '变压器', '开关', '连接线路']" :key="k" :value="k">{{ k }}</el-radio-button>
      </el-radio-group>
      <div class="tbl" data-testid="measure-table">
        <table v-if="cur" class="table-plain" style="margin-top: 10px">
          <thead><tr><th v-for="c in cols(cur[sub])" :key="c">{{ c }}</th></tr></thead>
          <tbody><tr v-for="(r, i) in cur[sub]" :key="i"><td v-for="c in cols(cur[sub])" :key="c" :class="{ mono: /ID|id/.test(c) }">{{ r[c] }}</td></tr></tbody>
        </table>
      </div>
      <p class="sub">变压器档位列里的 -999999 表示“该字段无值”（节点模型里没有档位信息），不是真实取值。</p>
    </div>

    <div class="two">
      <div class="card card-pad">
        <div class="card-title">测点 → 节点：逆向恢复与往返验证
          <el-button size="small" type="primary" :loading="rtBusy" data-testid="run-roundtrip" @click="runRoundtrip">运行往返验证</el-button></div>
        <p class="sub">按正向构造的逆过程，从测点表恢复 Bus / Branch / Gen，再与原节点数据逐项比对。</p>
        <div v-if="rt" data-testid="roundtrip-result">
          <div class="res" :class="rt.lossless_with_mapping ? 'ok' : 'bad'">
            {{ rt.lossless_with_mapping ? '往返一致：母线、支路、机组出力合计全部与原数据相同' : '往返存在差异' }}
          </div>
          <table class="table-plain">
            <tbody>
              <tr><th>母线</th><td>恢复 {{ rt.recovered.bus }} / 原始 {{ rt.original.bus }}，差异 {{ rt.mismatch.bus }}</td></tr>
              <tr><th>支路</th><td>恢复 {{ rt.recovered.branch }} / 原始 {{ rt.original.branch }}，差异 {{ rt.mismatch.branch }}</td></tr>
              <tr><th>机组（按母线合计）</th><td>{{ rt.recovered.gen_buses }} 个挂机组的母线，差异 {{ rt.mismatch.gen_bus_total }}</td></tr>
            </tbody>
          </table>
          <div class="amb">
            <b>为什么需要映射表</b>
            <p>没有映射表时，信息不能无损恢复：<b>{{ rt.ambiguities_without_mapping.multi_gen_buses }}</b> 个母线挂了不止一台机组（如母线 {{ rt.example_multi_gen?.[0] }}：{{ rt.example_multi_gen?.[1]?.join('、') }}），只能得到合计出力；<b>{{ rt.ambiguities_without_mapping.parallel_branch_groups }}</b> 组平行支路（如 {{ rt.example_parallel?.join('、') }}）无法只按首末端点区分回路。保留源记录键与映射版本即可无歧义地恢复。</p>
          </div>
        </div>
      </div>

      <div class="card card-pad">
        <div class="card-title">方案回写：节点结果 → 测点动作 <StatusBadge feature="m6.writeback" small /></div>
        <p class="sub">选一个已求解的任务，把方案里被开断的支路映射为虚拟开关动作清单。</p>
        <el-select v-model="tid" clearable placeholder="选择任务" style="width: 100%" data-testid="wb-task" @change="loadWb">
          <el-option v-for="t in tasks" :key="t.id" :value="t.id" :label="`${t.id} · ${t.instruction.slice(0, 26)}`" />
        </el-select>
        <div v-if="wb" data-testid="writeback-result" style="margin-top: 10px">
          <table v-if="wb.actions.length" class="table-plain">
            <thead><tr><th>时段</th><th>开关</th><th>支路</th><th>动作</th></tr></thead>
            <tbody><tr v-for="(a, i) in wb.actions" :key="i"><td>{{ a.period }}</td><td class="mono">{{ a.switch }}</td><td>{{ a.branch }}</td><td :class="a.action === '断开' ? 'lv-error' : 'lv-info'"><b>{{ a.action }}</b></td></tr></tbody>
          </table>
          <div v-else class="sub">该任务的方案没有开断动作。</div>
          <p class="sub">{{ wb.note }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 14px 0; }
.kpi { background: var(--c-surface); border: 1px solid var(--c-hairline); border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; box-shadow: var(--shadow); }
.kpi span { font-size: 12px; color: var(--c-muted); } .kpi b { font-size: 26px; color: var(--c-brand-blue); } .kpi em { font-style: normal; font-size: 11.5px; color: var(--c-faint); }
.kpi.hl { background: var(--grad-hero); border: none; } .kpi.hl span, .kpi.hl b { color: #fff; }
.steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
.st { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; background: var(--c-surface-2); border-radius: 10px; position: relative; font-size: 12.5px; color: var(--c-muted); line-height: 1.65; }
.st i { position: absolute; right: 12px; top: 8px; font-style: normal; font-size: 28px; font-weight: 800; color: rgba(31, 95, 196, 0.15); } .st b { color: var(--c-ink); font-size: 14px; }
.tbl { max-height: 360px; overflow: auto; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; align-items: start; }
@media (max-width: 1200px) { .two { grid-template-columns: 1fr; } }
.res { padding: 10px 14px; border-radius: 8px; font-weight: 600; margin: 8px 0; } .res.ok { background: var(--c-success-bg); color: var(--c-success); } .res.bad { background: var(--c-danger-bg); color: var(--c-danger); }
.amb { margin-top: 10px; padding: 10px 14px; background: var(--c-infer-bg); border-radius: 8px; font-size: 12.5px; line-height: 1.7; } .amb p { margin: 4px 0 0; }
</style>
