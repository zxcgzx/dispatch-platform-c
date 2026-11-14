<script setup lang="ts">
// 步骤 5：求解面板（黑盒）。模式标签“黑盒”、求解器与参数（来自 R）、运行日志（SSE 实时）、耗时分解。
// 三种模式：mock（不调用任何求解器）/ import（上传结果 JSON）/ external（执行 SOLVER_CMD）。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, ApiError } from '@/api/client'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'
import type { JobInfo, SolveResult } from '@/types/later'

const t = useTaskStore()
const info = ref<any>(null)
const mode = ref('mock')
const job = ref<JobInfo | null>(null)
const lines = ref<string[]>([])
const result = ref<SolveResult | null>(null)
const importErr = ref('')
const schemaOpen = ref(false)
const schema = ref<any>(null)
let es: EventSource | null = null

const v = computed(() => t.viewVersion ?? t.current)
const spec = computed(() => t.state?.versions.find((x) => x.version === v.value))
const blocked = computed(() => !!spec.value?.has_error)
const R = computed(() => t.spec?.solver_req)
const timings = computed(() => {
  const x = result.value?.timings_s ?? {}
  const f = (n?: number | null) => (n === null || n === undefined ? '—' : `${n.toFixed(2)} s`)
  return [{ k: '读数据', v: f(x.read) }, { k: '建模', v: f(x.build) }, { k: '求解', v: f(x.solve) }, { k: 'N−1 校核', v: f(x.n1_check) }]
})

onMounted(async () => {
  info.value = await api.get('/solver/info')
  mode.value = info.value.mode
  await loadResult()
})
onBeforeUnmount(() => es?.close())

async function loadResult() {
  if (!t.taskId || v.value === null) return
  const r = await api.get<{ result: SolveResult | null }>(`/tasks/${t.taskId}/results?version=${v.value}`)
  result.value = r.result
}
function stream(id: string) {
  es?.close()
  lines.value = []
  es = new EventSource(`/api/jobs/${id}/log`)
  es.onmessage = (e) => lines.value.push(JSON.parse(e.data))
  es.addEventListener('end', async (e: MessageEvent) => {
    es?.close()
    const d = JSON.parse(e.data)
    job.value = await api.get<JobInfo>(`/jobs/${id}`)
    if (d.status === 'done') await loadResult()
    else ElMessage.error(d.error ?? '求解失败')
    await t.refreshAfterResult()
  })
}
async function run() {
  if (!t.taskId || blocked.value) return
  await t.run(async () => {
    const j = await api.post<JobInfo>(`/tasks/${t.taskId}/solve`, { version: v.value, mode: mode.value })
    job.value = j
    result.value = null
    if (j.status === 'running') stream(j.id)           // 已结束的作业（mock 立即完成）不再开 SSE，直接取日志
    else {
      lines.value = (await api.get<any>(`/jobs/${j.id}`)).log
      if (j.status === 'done') await loadResult()
      else ElMessage.error(j.error ?? '求解失败')
      await t.refreshAfterResult()
    }
    t.say(`已启动求解作业 ${j.id}（${mode.value}）`, 'info')
  })
}
async function onFile(ev: Event) {
  importErr.value = ''
  const f = (ev.target as HTMLInputElement).files?.[0]
  if (!f) return
  try {
    const body = JSON.parse(await f.text())
    await api.post(`/tasks/${t.taskId}/results/import?version=${v.value}`, body)
    await loadResult()
    lines.value = [`导入结果：${f.name}（status = ${body.status}）`]
    ElMessage.success('结果已导入')
    await t.refreshAfterResult()
  } catch (e) {
    importErr.value = e instanceof ApiError ? e.message : (e as Error).message
  }
  ;(ev.target as HTMLInputElement).value = ''
}
async function showSchema() {
  schema.value = await api.get('/solver/result-schema')
  schemaOpen.value = true
}
const exampleJson = JSON.stringify({
  status: 'optimal', solver: 'ipopt', objective: 0.0, periods: 16, timings_s: { read: 0, build: 0, solve: 0, n1_check: 0 },
  branch_status: { L155: [1, 1, 0, 0] }, gen_p: { G237: [79.8, 79.8, 75.0, 75.0] }, bus_vm: { B43: [1.01, 1.01, 1.0, 1.0] },
  branch_flow: { L155: { pf: [], qf: [], pt: [], qt: [] } }, messages: [],
}, null, 1)
const mocked = computed(() => result.value?.status === 'mock')
const infeasible = computed(() => result.value?.status === 'infeasible')
const diag = ref<any>(null)
const diagBusy = ref(false)
async function runDiag() {
  diagBusy.value = true
  try { diag.value = await api.post(`/tasks/${t.taskId}/diagnose?version=${v.value}`) } finally { diagBusy.value = false }
}
</script>

<template>
  <div class="sp" data-testid="solve-panel">
    <section class="card card-pad">
      <div class="card-title">步骤 5 · 求解</div>
      <p class="sub">求解器作为黑盒接入：内置 HiGHS 可直接求解直流近似 OTS，商业求解器（COPT / Gurobi）与外部求解链经外部命令接入；<b>不做求解加速、调参、热启动</b>。</p>
      <div v-if="blocked" class="lv-error" data-testid="solve-blocked">v{{ v }} 校验有错误，不能进入求解：请先回到“规格确认”修正。</div>
      <div class="grid">
        <div>
          <div class="sub">模式</div>
          <el-radio-group v-model="mode" data-testid="solver-mode">
            <el-radio-button v-for="m in info?.modes ?? []" :key="m.id" :value="m.id">{{ m.id }}</el-radio-button>
          </el-radio-group>
          <p class="sub">{{ info?.modes?.find((m: any) => m.id === mode)?.label }}</p>
          <p v-if="mode === 'external'" class="sub">命令：<code>{{ info?.cmd || '未配置 SOLVER_CMD' }}</code></p>
        </div>
        <div>
          <div class="sub">求解要求 R（来自规格）</div>
          <div>求解器：<b>{{ R?.solver }}</b> · 时限 {{ R?.time_limit_s }} s · 容差 {{ R?.tolerance }}</div>
          <div class="sub">输出项：{{ R?.outputs?.join('、') }}</div>
        </div>
      </div>
      <div class="row" style="margin-top: 10px">
        <el-button v-if="mode !== 'import'" type="primary" :disabled="blocked || t.busy || job?.status === 'running'" data-testid="run-solve" @click="run">
          {{ mode === 'mock' ? '运行（mock，不调用求解器）' : mode === 'builtin' ? '运行求解' : '运行外部求解' }}
        </el-button>
        <template v-else>
          <label class="upload">
            <input type="file" accept=".json,application/json" data-testid="import-file" @change="onFile" />
          </label>
          <el-button size="small" text type="primary" @click="showSchema">查看结果格式（result_schema.json）</el-button>
        </template>
        <StatusBadge v-if="mode === 'external'" feature="m5.external" small />
      </div>
      <div v-if="importErr" class="lv-error" data-testid="import-error" style="margin-top: 6px">{{ importErr }}</div>
    </section>

    <section v-if="mocked" class="banner" data-testid="mock-banner">
      占位模式：未调用求解器，没有开断方案和出力调整。
    </section>

    <section v-if="infeasible" class="card card-pad diag" data-testid="diag-card">
      <div class="card-title">无解诊断 <StatusBadge feature="m4.iis" small />
        <el-button type="primary" size="small" :loading="diagBusy" data-testid="run-diag" @click="runDiag">定位冲突约束</el-button></div>
      <p class="sub">求解器没有找到可行方案。逐项放开限额、断面、开关次数、机组范围、停运等约束，看放开哪一项后模型变可行，那一项就是冲突来源。</p>
      <template v-if="diag">
        <div :class="diag.conflicts.length ? 'lv-warn' : 'sub'" data-testid="diag-msg">{{ diag.message }}</div>
        <ul class="cl"><li v-for="c in diag.conflicts" :key="c.id" :data-conflict="c.id"><b>{{ c.label }}</b><span class="sub">　建议：{{ c.hint }}</span></li></ul>
        <div class="sub">耗时 {{ diag.elapsed_s }} s</div>
      </template>
    </section>

    <section class="card card-pad">
      <div class="card-title">运行日志 <span v-if="job" class="sub">作业 {{ job.id }} · {{ job.status }} · {{ job.elapsed_s }} s</span></div>
      <pre class="log" data-testid="solve-log">{{ lines.length ? lines.join('\n') : '（尚无运行）' }}</pre>
    </section>

    <section class="card card-pad">
      <div class="card-title">耗时分解</div>
      <div class="row tm" data-testid="timings"><div v-for="x in timings" :key="x.k" class="tcell"><span class="sub">{{ x.k }}</span><b>{{ x.v }}</b></div></div>
      <div v-if="result" class="sub" style="margin-top: 6px">
        状态：<b>{{ result.status }}</b> · 求解器：{{ result.solver || '—' }} · 目标值：{{ result.objective ?? '—' }}
        <div v-for="m in result.messages" :key="m">{{ m }}</div>
      </div>
    </section>

    <el-dialog v-model="schemaOpen" title="结果 JSON 格式" width="720px" append-to-body>
      <p class="sub">import 与 external 共用。数组长度等于 periods；branch_status 可以只给有变化的支路，没给的按断面状态处理。</p>
      <pre class="log">{{ exampleJson }}</pre>
      <details><summary>JSON Schema</summary><pre class="log">{{ JSON.stringify(schema, null, 1) }}</pre></details>
    </el-dialog>
  </div>
</template>

<style scoped>
.sp { display: flex; flex-direction: column; gap: var(--sp-3); }
.cl { margin: 6px 0; padding-left: 18px; line-height: 1.9; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-4); }
.banner { background: var(--c-st-black-bg); border: 1px dashed var(--c-st-black); border-radius: var(--radius); padding: 12px 16px; font-weight: 600; }
.log { background: #111; color: #d6e2d6; padding: 10px 12px; border-radius: var(--radius-sm); font-size: var(--fs-xs); line-height: 1.6; max-height: 260px; overflow: auto; white-space: pre-wrap; margin: 0; }
.tm { gap: 24px; }
.tcell { display: flex; flex-direction: column; }
.tcell b { font-size: var(--fs-lg); }
</style>
