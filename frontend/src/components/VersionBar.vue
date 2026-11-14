<script setup lang="ts">
// 底栏：规格版本链（v1 → v2 → …，点击看差异；选任意两版看规格差异）与“运行日志”抽屉（该任务的后端日志）。
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import { useTaskStore } from '@/stores/task'
import type { SpecDiff } from '@/types/api'

const t = useTaskStore()
const diffOpen = ref(false)
const logOpen = ref(false)
const logText = ref('')
const a = ref('1')
const b = ref('2')
const diff = ref<SpecDiff | null>(null)
const diffErr = ref('')

const chain = computed(() => t.versions)
const draftExists = computed(() => !!t.state?.spec && (t.current === null || t.state.draft_dirty))
const options = computed(() => [
  ...t.versions.map((v) => ({ value: String(v.version), label: `v${v.version}` })),
  ...(t.state?.spec ? [{ value: 'draft', label: '当前草稿' }] : []),
])

async function showDiff(x: string, y: string) {
  a.value = x
  b.value = y
  diffOpen.value = true
  await load()
}
async function load() {
  diffErr.value = ''
  try {
    diff.value = await t.diff(a.value, b.value)
  } catch (e: any) {
    diff.value = null
    diffErr.value = e.message
  }
}
async function clickVersion(v: number) {
  const prev = t.versions.find((x) => x.version === v)?.parent_version
  t.viewVersion = v
  await t.loadVersionArtifacts(v)
  if (prev) await showDiff(String(prev), String(v))
  else {
    diff.value = null
    a.value = String(v)
    b.value = t.state?.spec ? 'draft' : String(v)
    diffOpen.value = true
    await load()
  }
}
async function openLog() {
  if (!t.taskId) return
  logOpen.value = true
  logText.value = await api.get<string>(`/tasks/${t.taskId}/log`)
}
const fieldLabel: Record<string, string> = {
  operation: '操作', direction: '方向', value: '数值', periods: '时段', source: '来源', confirmed: '已确认', evidence: '原文依据', inference_chain: '推断链',
  kind: '类别', params: '参数', custom_code: '自定义代码', problem: '问题类型', n_minus_1: 'N−1', contingency_rule: '事故集规则', switchable_rule: '可开断集合规则',
  periods_: '时段数', solver: '求解器', time_limit_s: '时限', tolerance: '容差', outputs: '输出项', system: '系统', step_min: '步长',
}
function show(v: any) {
  if (v === null || v === undefined) return '—'
  if (Array.isArray(v)) return v.length ? v.join(',') : '全部'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
</script>

<template>
  <footer class="vb card" data-testid="version-bar">
    <span class="sub">规格版本</span>
    <div class="chain" data-testid="version-chain">
      <template v-for="(v, i) in chain" :key="v.version">
        <button class="ver" :class="{ cur: t.viewVersion === v.version, err: v.has_error }" :data-version="v.version" :title="v.change_reason ?? ''" @click="clickVersion(v.version)">
          <b>v{{ v.version }}</b>
          <span class="rs">{{ v.change_reason ?? '指令解析' }}</span>
        </button>
        <span v-if="i < chain.length - 1 || draftExists" class="arr">→</span>
      </template>
      <button v-if="draftExists" class="ver draft" data-version="draft" @click="showDiff(String(t.current ?? 1), 'draft')">
        <b>v{{ (t.current ?? 0) + 1 }}</b><span class="rs">{{ t.state?.draft_change_reason ?? '待确认' }}</span>
      </button>
      <span v-if="!chain.length && !draftExists" class="sub">尚无版本（解析指令后出现草稿，确认后生成 v1）</span>
    </div>
    <span class="grow" />
    <el-button size="small" :disabled="options.length < 2" data-testid="open-diff" @click="showDiff(options[0]?.value ?? '1', options.at(-1)?.value ?? '1')">比较版本</el-button>
    <el-button size="small" :disabled="!t.taskId" data-testid="open-log" @click="openLog">运行日志 ▸</el-button>

    <el-dialog v-model="diffOpen" title="规格差异" width="760px" append-to-body>
      <div class="row" style="margin-bottom: 8px">
        <el-select v-model="a" size="small" style="width: 120px" data-testid="diff-a" @change="load"><el-option v-for="o in options" :key="o.value" :value="o.value" :label="o.label" /></el-select>
        <span>→</span>
        <el-select v-model="b" size="small" style="width: 120px" data-testid="diff-b" @change="load"><el-option v-for="o in options" :key="o.value" :value="o.value" :label="o.label" /></el-select>
        <span v-if="diff" class="sub">共 {{ diff.total }} 处差异</span>
      </div>
      <div v-if="diffErr" class="lv-error">{{ diffErr }}</div>
      <div v-if="diff" data-testid="diff-body">
        <p v-if="diff.change_reason_b" class="sub">本版改动原因：<b>{{ diff.change_reason_b }}</b></p>
        <p v-if="diff.instruction_changed" class="sub">指令变化：<br />A：{{ diff.instruction_a }}<br />B：{{ diff.instruction_b }}</p>
        <p v-if="!diff.total && !diff.instruction_changed" class="sub">两版规格没有差异。</p>
        <template v-for="g in [{ k: 'delta_pi', n: '参数修改 Δπ' }, { k: 'structural', n: '结构修改 s' }] as const" :key="g.k">
          <div v-if="diff[g.k].added.length || diff[g.k].removed.length || diff[g.k].modified.length" class="grp">
            <h4>{{ g.n }}</h4>
            <div v-for="x in diff[g.k].added" :key="'a' + x.id" class="df add" data-kind="added">＋ 新增 <b>{{ x.key }}</b> <span class="sub">{{ x.id }}</span></div>
            <div v-for="x in diff[g.k].removed" :key="'r' + x.id" class="df del" data-kind="removed">－ 删除 <b>{{ x.key }}</b> <span class="sub">{{ x.id }}</span></div>
            <div v-for="x in diff[g.k].modified" :key="'m' + x.key" class="df mod" data-kind="modified">
              ～ 修改 <b>{{ x.key }}</b>
              <div v-for="c in x.changes" :key="c.field" class="sub">　{{ fieldLabel[c.field] ?? c.field }}：<s>{{ show(c.a) }}</s> → <b>{{ show(c.b) }}</b></div>
            </div>
          </div>
        </template>
        <div v-if="diff.omega.length" class="grp"><h4>基础模型 ω</h4><div v-for="c in diff.omega" :key="c.field" class="df mod">{{ fieldLabel[c.field] ?? c.field }}：<s>{{ show(c.a) }}</s> → <b>{{ show(c.b) }}</b></div></div>
        <div v-if="diff.solver_req.length" class="grp"><h4>求解要求 R</h4><div v-for="c in diff.solver_req" :key="c.field" class="df mod">{{ fieldLabel[c.field] ?? c.field }}：<s>{{ show(c.a) }}</s> → <b>{{ show(c.b) }}</b></div></div>
      </div>
    </el-dialog>

    <el-drawer v-model="logOpen" title="运行日志" size="520px" append-to-body direction="rtl">
      <pre class="log" data-testid="log-text">{{ logText }}</pre>
    </el-drawer>
  </footer>
</template>

<style scoped>
.vb { flex: none; display: flex; align-items: center; gap: 12px; padding: 8px 14px; min-height: 52px; }
.chain { display: flex; align-items: center; gap: 6px; overflow-x: auto; }
.ver { font: inherit; border: 1px solid var(--c-border); background: var(--c-surface); border-radius: var(--radius); padding: 3px 12px; cursor: pointer; display: flex; flex-direction: column; align-items: flex-start; max-width: 220px; }
.ver .rs { font-size: var(--fs-xs); color: var(--c-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
.ver.cur { border: 2px solid var(--c-primary); background: var(--c-primary-bg); }
.ver.err { border-color: var(--c-danger); }
.ver.draft { border-style: dashed; background: var(--c-surface-2); }
.arr { color: var(--c-muted); }
.grp { margin-top: 10px; }
.grp h4 { margin: 0 0 4px; font-size: var(--fs-md); }
.df { padding: 6px 10px; border-radius: var(--radius-sm); margin-bottom: 4px; font-size: var(--fs-sm); }
.df.add { background: var(--c-success-bg); } .df.del { background: var(--c-danger-bg); } .df.mod { background: var(--c-warn-bg); }
.log { white-space: pre-wrap; font-size: var(--fs-xs); line-height: 1.7; }
</style>
