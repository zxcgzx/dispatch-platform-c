<script setup lang="ts">
// 步骤 7：风险评估。4.2 指标卡片（调整前=断面真实数据；调整后=求解结果，mock 显示“—”）、课题 3 风险、反馈方式（协商 / Reward）、调整建议。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'
import type { Evaluation, Suggestion } from '@/types/later'

const t = useTaskStore()
const ev = ref<Evaluation | null>(null)
const picked = ref<Record<string, boolean>>({})
const vals = reactive<Record<string, Record<string, any>>>({})
const mode = ref('negotiate')
const v = computed(() => t.viewVersion ?? t.current)
const m = computed(() => ev.value?.metrics)
const pct = (x: number | null | undefined) => (x === null || x === undefined ? '—' : (x * 100).toFixed(1) + '%')
const num = (x: number | null | undefined, d = 3) => (x === null || x === undefined ? '—' : x.toFixed(d))
const riskColor = computed(() => ({ 低: 'success', 中: 'warning', 高: 'danger' } as const)[ev.value?.risk?.risk_level ?? '低'])

onMounted(load)
watch(() => [t.viewVersion, t.resultTick], load)
async function load() {
  if (!t.taskId || v.value === null) return
  mode.value = t.state?.task.feedback_mode ?? 'negotiate'
  const e = await api.get<Evaluation>(`/tasks/${t.taskId}/evaluation?version=${v.value}`)
  ev.value = e.evaluated ? e : null
  if (!e.evaluated) await evaluate()
}
async function evaluate() {
  await t.run(async () => {
    ev.value = (await api.post<Evaluation>(`/tasks/${t.taskId}/evaluate?version=${v.value}`)) as any
    picked.value = {}
    t.state = await api.get(`/tasks/${t.taskId}`)
  })
}
async function setMode(x: string) {
  mode.value = x
  await api.post(`/tasks/${t.taskId}/feedback-mode`, { mode: x })
}
function fieldLabel(f: string) {
  return ({ limit_mw: '断面限额（MW）', k: '每时段次数上限 k', value: '数值（缩放系数 / 设定值）', target: '对象编号', branches: '断面支路' } as Record<string, string>)[f] ?? f
}
function valsOf(s: Suggestion) { return (vals[s.id] ??= {}) }
async function adjust() {
  const sel = (ev.value?.suggestions ?? []).filter((s) => picked.value[s.id])
  if (!sel.length) return ElMessage.warning('请至少勾选一条建议')
  for (const s of sel) for (const f of s.fields_needed) if (valsOf(s)[f] === undefined || valsOf(s)[f] === '' || valsOf(s)[f] === null) return ElMessage.warning(`建议 ${s.id} 的“${fieldLabel(f)}”需要你填写（系统不替你定数值）`)
  await t.run(async () => {
    t.state = await api.post(`/tasks/${t.taskId}/adjust`, { version: v.value, picks: sel.map((s) => ({ id: s.id, values: valsOf(s) })) })
    t.say(`已由 v${v.value} 的风险评估生成 v${t.state!.spec!.version} 草稿，回到步骤 3 确认。`, 'info')
    t.step = 3
    t.tab = 'spec'
    t.report = null
    await t.refreshPreview()
  })
}
const n1 = computed(() => m.value?.before?.n1)
const cmdp = ref<any>(null)
async function loadCmdp() {
  if (!t.taskId || v.value === null) return
  cmdp.value = await api.get(`/tasks/${t.taskId}/cmdp?version=${v.value}`)
}
watch(mode, (x) => { if (x === 'reward' && !cmdp.value) void loadCmdp() })
// Reward 分解：每类安全代价取调整后（没有结果时取调整前）的度量，奖励 = −(目标) − Σ λ·代价
const rewardParts = computed(() => {
  const b = m.value?.after ?? m.value?.before
  if (!b) return []
  const n1x = b.n1
  return [
    { k: '负载率越限条数', v: b.load_rate?.n_violation ?? 0 },
    { k: 'N−1 不通过事故数', v: n1x?.failed_count ?? 0 },
    { k: '电压越限母线数', v: b.voltage?.n_out ?? '—' },
  ]
})
</script>

<template>
  <div v-if="m" class="rk" data-testid="risk-panel">
    <section class="card card-pad risk" :class="ev?.risk?.risk_level" data-testid="risk-card">
      <div class="card-title">课题 3 风险评估 <StatusBadge feature="m7.risk" />
        <el-tag :type="riskColor" size="large" effect="dark" data-testid="risk-level">风险：{{ ev?.risk?.risk_level }}</el-tag></div>
      <div class="sub">{{ ev?.risk?.based_on }}</div>
      <ul class="reasons"><li v-for="r in ev?.risk?.reasons" :key="r.code">{{ r.text }}</li></ul>
      <div v-if="ev?.risk?.reward !== null && ev?.risk?.reward !== undefined" class="sub">Reward：{{ ev?.risk?.reward }}</div>
    </section>

    <div class="cards">
      <section class="card card-pad mc" data-testid="card-loadrate">
        <div class="card-title">负载率 ρ <StatusBadge feature="m7.loadrate" small /></div>
        <table class="table-plain">
          <thead><tr><th /><th>调整前（断面）</th><th>调整后（结果）</th></tr></thead>
          <tbody>
            <tr><th>最大值</th><td>{{ pct(m.before.load_rate.max) }}</td><td>{{ pct(m.after?.load_rate?.max) }}</td></tr>
            <tr><th>平均值</th><td>{{ pct(m.before.load_rate.mean) }}</td><td>{{ pct(m.after?.load_rate?.mean) }}</td></tr>
            <tr><th>≥ {{ m.before.load_rate.overload_threshold * 100 }}% 条数</th><td>{{ m.before.load_rate.n_overload }}</td><td>{{ m.after?.load_rate?.n_overload ?? '—' }}</td></tr>
            <tr><th>≥ {{ m.before.load_rate.violation_threshold * 100 }}% 条数</th><td>{{ m.before.load_rate.n_violation }}</td><td>{{ m.after?.load_rate?.n_violation ?? '—' }}</td></tr>
          </tbody>
        </table>
        <div class="sub">只算 RATE_A &gt; 0 的 {{ m.before.load_rate.n_evaluated }} 条支路；{{ m.before.load_rate.n_unlimited }} 条 RATE_A = 0 视为不限。</div>
      </section>

      <section class="card card-pad mc" data-testid="card-voltage">
        <div class="card-title">电压偏移 ΔV <StatusBadge feature="m7.voltage" small /></div>
        <table class="table-plain">
          <thead><tr><th /><th>调整前（断面）</th><th>调整后（结果）</th></tr></thead>
          <tbody>
            <tr><th>最大值</th><td>{{ num(m.before.voltage.max) }}</td><td>{{ num(m.after?.voltage?.max) }}</td></tr>
            <tr><th>平均值</th><td>{{ num(m.before.voltage.mean, 4) }}</td><td>{{ num(m.after?.voltage?.mean, 4) }}</td></tr>
            <tr><th>越限母线数</th><td>{{ m.before.voltage.n_out }}</td><td>{{ m.after?.voltage?.n_out ?? '—' }}</td></tr>
          </tbody>
        </table>
        <div class="sub">{{ m.before.voltage.note }}</div>
      </section>

      <section class="card card-pad mc" data-testid="card-n1">
        <div class="card-title">N−1 通过率 <StatusBadge feature="m7.n1" small /><el-tag size="small" type="warning" effect="plain">直流近似筛查 · 非交流 N−1 校核</el-tag></div>
        <div class="big" data-testid="n1-rate">{{ pct(n1.pass_rate) }}<span class="sub"> 调整前：通过 {{ n1.passed }} / 评估 {{ n1.evaluated }}</span></div>
        <div class="sub">调整后：{{ m.after ? `${pct(m.after.n1.pass_rate)}（通过 ${m.after.n1.passed} / ${m.after.n1.evaluated}）` : '—' }}</div>
        <div class="sub">事故集：{{ n1.rule_name }}（{{ n1.contingency_total }} 条）· 方法：PTDF / LODF，事故后 f′ = f + LODF·f_c，|f′| ≤ RATE_A 即通过</div>
        <div v-if="n1.islanding.count" class="sub lv-warn">孤岛事故 {{ n1.islanding.count }} 条（不进 LODF）：累计净负荷约 {{ n1.islanding.net_load_mw_total }} MW；单次最大 {{ n1.islanding.largest?.contingency }}，净注入 {{ n1.islanding.largest?.net_injection_mw }} MW</div>
        <div v-if="n1.failed_count" class="lv-error">不通过 {{ n1.failed_count }} 个事故；最差 {{ n1.failed[0].contingency }} → {{ n1.failed[0].worst }}（{{ pct(n1.failed[0].worst_rho) }}）</div>
      </section>

      <section class="card card-pad mc todo">
        <div class="card-title">静态电压稳定裕度 <StatusBadge feature="m7.vsm" small /></div>
        <div class="sub">{{ m.unimplemented.vsm }}</div>
        <div class="card-title" style="margin-top: 14px">新能源消纳率 <StatusBadge feature="m7.renewable" small /></div>
        <div class="sub">{{ m.unimplemented.renewable }}</div>
      </section>
    </div>
    <div v-if="m.after_note" class="sub note" data-testid="after-note">{{ m.after_note }}</div>

    <section class="card card-pad">
      <div class="card-title">反馈与动态调整
        <el-radio-group :model-value="mode" size="small" data-testid="feedback-mode" @update:model-value="(x: any) => setMode(x)">
          <el-radio-button value="negotiate">协商</el-radio-button><el-radio-button value="reward">Reward</el-radio-button>
        </el-radio-group></div>

      <div v-if="mode === 'reward'" class="reward" data-testid="reward-panel">
        <div class="sub"><StatusBadge feature="m7.reward" small /> 风险等级折算成奖励，反馈给强化学习；课题 3 接口返回 <code>reward</code>（number | null）。</div>
        <table class="table-plain">
          <thead><tr><th>安全代价项</th><th>当前值</th></tr></thead>
          <tbody><tr v-for="p in rewardParts" :key="p.k"><td>{{ p.k }}</td><td><b>{{ p.v }}</b></td></tr></tbody>
        </table>
        <div class="sub">奖励 r = −（偏离当前方式 + 目标项） − Σ λ<sub>i</sub>·代价<sub>i</sub>；系数 λ 由课题 3 给出，未给出时不折算。</div>
        <div v-if="cmdp" class="cmdp" data-testid="cmdp-card">
          <div class="card-title">OTS → CMDP <StatusBadge feature="m10.cmdp" small /></div>
          <div class="kv"><span>状态维度</span><b>{{ cmdp.state.dim }}</b><span>每步动作数</span><b>{{ cmdp.action.per_step_total }}（0-1：{{ cmdp.action.binary }}）</b><span>时段</span><b>{{ cmdp.periods }}</b><span>全时域动作</span><b>{{ cmdp.horizon_actions }}</b></div>
          <div class="sub">{{ cmdp.reward.expr }}</div>
          <ul class="cl"><li v-for="c in cmdp.costs" :key="c.id"><b>{{ c.name }}</b>　<span class="sub">{{ c.expr }}</span></li></ul>
          <div class="sub">{{ cmdp.note }}</div>
        </div>
      </div>
      <template v-else>
        <p class="sub">按风险原因生成调整建议，每条是一条待确认的 Δπ 或 s；<b>数值一律留空，由你填写</b>。勾选后生成新一版规格并回到步骤 3。</p>
        <div v-if="!ev?.suggestions?.length" class="empty" data-testid="no-suggestions">当前风险下没有调整建议（风险低，或没有可操作的原因）。</div>
        <div v-for="s in ev?.suggestions" :key="s.id" class="sg" :data-sid="s.id">
          <el-checkbox v-model="picked[s.id]" :data-testid="'pick-' + s.id"><b class="mono">{{ s.id }}</b> {{ s.kind === 'dp' ? 'Δπ' : 's' }} · {{ s.reason }}</el-checkbox>
          <div v-if="picked[s.id]" class="fields">
            <label v-for="f in s.fields_needed" :key="f"><span>{{ fieldLabel(f) }}</span>
              <el-input v-model="valsOf(s)[f]" size="small" :placeholder="f === 'branches' ? 'L428,L429' : '请填写'" :data-testid="`val-${s.id}-${f}`" /></label>
          </div>
        </div>
        <div class="row" style="margin-top: 10px">
          <el-button type="primary" :disabled="!ev?.suggestions?.length || t.busy" data-testid="adjust-btn" @click="adjust">生成新版本并回到步骤 3</el-button>
          <el-button size="small" @click="evaluate">重新评估</el-button>
        </div>
      </template>
    </section>
  </div>
  <div v-else class="sub empty">评估中…</div>
</template>

<style scoped>
.rk { display: flex; flex-direction: column; gap: var(--sp-3); }
.risk.高 { border-color: var(--c-danger); } .risk.中 { border-color: var(--c-infer-line); } .risk.低 { border-color: var(--c-success); }
.reasons { margin: 6px 0; padding-left: 18px; font-size: var(--fs-sm); line-height: 1.8; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: var(--sp-3); }
.mc th:first-child { width: 120px; }
.big { font-size: 28px; font-weight: 700; margin: 4px 0; }
.todo { border-style: dashed; }
.empty { padding: var(--sp-4); border: 1px dashed var(--c-border); border-radius: var(--radius); }
.sg { padding: 8px 10px; border: 1px solid var(--c-hairline); border-radius: var(--radius); margin-bottom: 6px; }
.fields { display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0 0 24px; }
.fields label { display: flex; flex-direction: column; gap: 2px; font-size: var(--fs-xs); color: var(--c-muted); }
.note { padding: 0 4px; }
.reward { display: flex; flex-direction: column; gap: 10px; }
.cmdp { border: 1px dashed var(--c-border); border-radius: var(--radius); padding: 10px 14px; }
.kv { display: grid; grid-template-columns: auto auto auto auto; gap: 4px 14px; font-size: var(--fs-sm); margin: 6px 0; }
.kv span { color: var(--c-muted); }
.cl { margin: 6px 0; padding-left: 18px; line-height: 1.8; }
</style>
