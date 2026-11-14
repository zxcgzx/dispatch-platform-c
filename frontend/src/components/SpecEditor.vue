<script setup lang="ts">
// 规格标签页：ω 区、Δπ 可编辑表格、s 区（算子卡片 + 参数表单）、R 区、底部“确认并生成代码”“退回修改”和规模摘要。
// 推断项整行琥珀色，未确认时“确认并生成代码”不可点。所有修改先在本地草稿里改，点“保存修改”才写回后端。
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'
import type { DeltaPi, ModelSpec, StructuralOp } from '@/types/api'

const t = useTaskStore()
const local = ref<ModelSpec | null>(null)
const objects = ref<{ bus: any[]; branch: any[]; gen: any[] }>({ bus: [], branch: [], gen: [] })
const dirty = ref(false)
const reasonDlg = ref(false)
const reason = ref('')

let objLoading: Promise<void> | null = null
function ensureObjects() {          // 对象选择器第一次展开时才加载（130 KB）
  objLoading ??= api.get<any>('/objects').then((d) => { objects.value = d }).catch(() => { objLoading = null })
  return objLoading
}
onMounted(() => t.loadMeta())
watch(() => t.spec, (s) => {
  local.value = s ? JSON.parse(JSON.stringify(s)) : null
  dirty.value = false
}, { immediate: true, deep: true })

const wl = computed(() => t.meta?.whitelist ?? {})
const ops = computed(() => t.meta?.operators ?? {})
const rules = computed(() => t.meta?.rules)
const compLabel: Record<string, string> = { bus: '母线', gen: '机组', branch: '支路' }
const opLabel: Record<string, string> = { scale: '按比例', set: '设定为', add: '增加' }
const dirLabel: Record<string, string> = { increase: '调高', decrease: '调低', set_zero: '置 0' }

function mark() { dirty.value = true }
function paramsOf(comp: string) { return Object.keys(wl.value[comp] ?? {}) }
function opsOf(d: DeltaPi) { return wl.value[d.component]?.[d.param]?.ops ?? [] }
function dirsOf(d: DeltaPi) { return wl.value[d.component]?.[d.param]?.dirs ?? [] }
function optionsFor(comp: string) { return objects.value[comp as 'bus'] ?? [] }
function periodNums(n: number) { return Array.from({ length: n }, (_, i) => i + 1) }
function periodLabel(p: number) { return t.state ? `${p}` : `${p}` }

function onComponent(d: DeltaPi) {
  d.target = ''
  d.param = paramsOf(d.component)[0]
  onParam(d)
}
function onParam(d: DeltaPi) {
  const o = opsOf(d)
  if (d.source === 'explicit') {
    d.operation = (o.includes(d.operation as string) ? d.operation : o[0]) as any
    d.direction = null
  } else {
    const dirs = dirsOf(d)
    d.direction = (dirs.includes(d.direction as string) ? d.direction : dirs[0]) as any
  }
  mark()
}
function onSource(d: DeltaPi) {
  if (d.source === 'explicit') {
    d.direction = null
    d.operation = (opsOf(d)[0] ?? 'scale') as any
    d.confirmed = false
    d.inference_chain = null
  } else {
    d.operation = null
    d.value = null
    d.direction = (dirsOf(d)[0] ?? 'decrease') as any
    d.confirmed = false
    d.pending_fields = Array.from(new Set([...(d.pending_fields ?? []), 'value']))
  }
  mark()
}
function onValue(d: DeltaPi) {
  if (d.value !== null && d.value !== undefined && (d.value as any) !== '') d.pending_fields = (d.pending_fields ?? []).filter((f) => f !== 'value')
  else if (d.source === 'inferred') d.confirmed = false
  mark()
}
function onPeriods(d: DeltaPi) {
  if ((d.periods ?? []).length || true) d.pending_fields = (d.pending_fields ?? []).filter((f) => f !== 'periods')
  mark()
}
function allPeriods(d: DeltaPi) { d.periods = []; d.pending_fields = (d.pending_fields ?? []).filter((f) => f !== 'periods'); mark() }
function addDelta() {
  if (!local.value) return
  const n = Math.max(0, ...local.value.delta_pi.map((d) => +d.id.split('-')[1] || 0)) + 1
  local.value.delta_pi.push({
    id: `dp-${n}`, component: 'bus', target: '', param: 'PD', operation: 'scale', direction: null, value: 1, periods: [],
    source: 'explicit', evidence: '', inference_chain: null, confirmed: false, pending_fields: [], origin: null,
  } as DeltaPi)
  mark()
}
function removeDelta(i: number) { local.value?.delta_pi.splice(i, 1); mark() }

// ---- s 区
const kindLabel: Record<string, string> = { problem: '问题类型', constraint: '约束', objective: '目标项' }
function addOperator(opId: string) {
  if (!local.value || !opId) return
  const o = ops.value[opId]
  const n = Math.max(0, ...local.value.structural.map((s) => +s.id.split('-')[1] || 0)) + 1
  const params: Record<string, any> = {}
  Object.entries(o.params).forEach(([k, d]: [string, any]) => {
    params[k] = d.default ?? (d.type === 'list_branch' ? [] : null)
  })
  local.value.structural.push({ id: `s-${n}`, kind: o.kind as any, op_id: opId, params, source: 'explicit', evidence: '', custom_code: null, origin: null, pending_fields: Object.keys(params).filter((k) => params[k] === null && !o.params[k].nullable) } as StructuralOp)
  mark()
}
function removeOperator(i: number) { local.value?.structural.splice(i, 1); mark() }
function setParam(s: StructuralOp, k: string, v: any) {
  s.params[k] = v
  if (v !== null && v !== '' && !(Array.isArray(v) && !v.length)) s.pending_fields = (s.pending_fields ?? []).filter((f) => f !== k)
  mark()
}
function branchesText(s: StructuralOp) { return ((s.params as any).branches ?? []).join(',') }
function setBranches(s: StructuralOp, v: string) {
  setParam(s, 'branches', v.split(/[,，、\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean))
}
function numVal(v: any) { return v === null || v === undefined ? undefined : v }
function paramError(s: StructuralOp, k: string): boolean { return (s.pending_fields ?? []).includes(k) }

// ---- 保存 / 确认
async function save() {
  if (!local.value) return
  await t.saveSpec(local.value)
  dirty.value = false
  ElMessage.success('规格草稿已保存')
}
async function confirmClick() {
  if (dirty.value) await save()
  if (t.state?.confirm_blockers.length) return
  if (t.current !== null && t.state?.draft_dirty) {
    reason.value = ''
    reasonDlg.value = true
    return
  }
  await t.confirm()
}
async function confirmWithReason() {
  reasonDlg.value = false
  await t.confirm(reason.value.trim() || undefined)
}
async function back() {
  // 退回修改：回到步骤 2，重新解析（保留已确认的版本；草稿回到解析结果）
  t.step = 2
  await t.reparse()
}

const blockers = computed(() => (dirty.value ? ['有未保存的修改，请先保存'] : []).concat(t.blockers))
const canConfirm = computed(() => !!local.value && !t.busy && (t.blockers.length === 0))
const scale = computed(() => t.scale)
const inferredCount = computed(() => (local.value?.delta_pi ?? []).filter((d) => d.source === 'inferred').length)
const itemHighlight = (id: string) => t.focus?.id === id
function focusItem(id: string) { t.setFocus(id, 'spec') }
function fmt(n: number | undefined) { return n === undefined ? '—' : n.toLocaleString('zh-CN') }
</script>

<template>
  <div v-if="local" class="spec" data-testid="spec-editor">
    <!-- ω -->
    <section class="card card-pad">
      <div class="card-title">基础模型 ω <span class="sub">N−1 是 ω 的默认设置（任务书要求），s 只放 ω 之外的扩展</span></div>
      <div class="omega">
        <label>系统<el-input v-model="local.omega.system" size="small" disabled /></label>
        <label>问题类型
          <el-select v-model="local.omega.problem" size="small" data-testid="omega-problem" @change="mark">
            <el-option value="multi_period_ac_ots" label="多时段 AC-OTS" /><el-option value="multi_period_acopf" label="多时段 AC-OPF（固定拓扑）" />
          </el-select>
        </label>
        <label>时段<el-input :model-value="`${local.omega.periods} × ${local.omega.step_min} 分钟`" size="small" disabled /></label>
        <label>N−1<br /><el-switch v-model="local.omega.n_minus_1" data-testid="omega-n1" @change="mark" /></label>
        <label>事故集规则
          <el-select v-model="local.omega.contingency_rule" size="small" :disabled="!local.omega.n_minus_1" @change="mark">
            <el-option v-for="(n, k) in rules?.contingency_rules" :key="k" :value="k as string" :label="n" />
          </el-select>
        </label>
        <label>可开断集合规则
          <el-select v-model="local.omega.switchable_rule" size="small" data-testid="omega-switchable" @change="mark">
            <el-option v-for="(n, k) in rules?.switchable_rules" :key="k" :value="k as string" :label="n" />
          </el-select>
        </label>
      </div>
    </section>

    <!-- Δπ -->
    <section class="card card-pad">
      <div class="card-title">参数修改 Δπ
        <el-button size="small" type="primary" plain data-testid="add-delta" @click="addDelta">+ 添加一项</el-button>
        <span v-if="inferredCount" class="infer-tag">含 {{ inferredCount }} 项推断</span>
      </div>
      <div class="scroll-x">
        <table class="table-plain dp" data-testid="delta-table">
          <thead><tr>
            <th style="width: 52px">编号</th><th>类型</th><th style="min-width: 128px">对象</th><th>参数</th><th>操作 / 方向</th><th>数值</th><th style="min-width: 130px">时段</th><th>来源</th><th>原文依据</th><th />
          </tr></thead>
          <tbody>
            <tr v-if="!local.delta_pi.length"><td colspan="10" class="sub">没有参数修改</td></tr>
            <tr
              v-for="(d, i) in local.delta_pi" :key="d.id" :data-item="d.id" :data-source="d.source"
              :class="{ 'infer-row': d.source === 'inferred', focus: itemHighlight(d.id) }" @click="focusItem(d.id)"
            >
              <td class="mono">{{ d.id }}</td>
              <td>
                <el-select v-model="d.component" size="small" style="width: 76px" @change="onComponent(d)">
                  <el-option v-for="(n, k) in compLabel" :key="k" :value="k as string" :label="n" />
                </el-select>
              </td>
              <td>
                <el-select v-model="d.target" size="small" filterable allow-create default-first-option placeholder="搜索 B / L / G 编号" style="width: 128px" :data-testid="'target-' + d.id" @visible-change="ensureObjects" @change="mark">
                  <el-option v-for="o in optionsFor(d.component)" :key="o.id" :value="o.id" :label="o.label" />
                </el-select>
              </td>
              <td>
                <el-select v-model="d.param" size="small" style="width: 104px" @change="onParam(d)">
                  <el-option v-for="p in paramsOf(d.component)" :key="p" :value="p" :label="p" />
                </el-select>
              </td>
              <td>
                <el-select v-if="d.source === 'explicit'" v-model="d.operation" size="small" style="width: 92px" @change="mark">
                  <el-option v-for="o in opsOf(d)" :key="o" :value="o" :label="opLabel[o]" />
                </el-select>
                <el-select v-else v-model="d.direction" size="small" style="width: 92px" @change="mark">
                  <el-option v-for="o in dirsOf(d)" :key="o" :value="o" :label="dirLabel[o]" />
                </el-select>
              </td>
              <td>
                <el-input-number
                  :model-value="numVal(d.value)" size="small" :controls="false" style="width: 80px" :step="0.1" :precision="4"
                  :placeholder="d.source === 'inferred' ? '待确认' : '数值'" :data-testid="'value-' + d.id"
                  @update:model-value="(v: number | undefined) => { d.value = v ?? null; onValue(d) }"
                />
                <div v-if="d.pending_fields?.includes('value')" class="lv-warn tiny">幅度待填</div>
              </td>
              <td>
                <el-select v-model="d.periods" multiple collapse-tags collapse-tags-tooltip size="small" placeholder="全部时段" style="width: 118px" :data-testid="'periods-' + d.id" @change="onPeriods(d)">
                  <el-option v-for="p in periodNums(local.omega.periods)" :key="p" :value="p" :label="`第 ${p} 时段`" />
                </el-select>
                <el-button size="small" text type="primary" @click.stop="allPeriods(d)">全部</el-button>
                <div v-if="d.pending_fields?.includes('periods')" class="lv-warn tiny">时段待定</div>
              </td>
              <td>
                <el-select v-model="d.source" size="small" style="width: 78px" @change="onSource(d)">
                  <el-option value="explicit" label="明确" /><el-option value="inferred" label="推断" />
                </el-select>
              </td>
              <td class="ev">
                <el-input v-model="d.evidence" size="small" type="textarea" :rows="2" resize="none" @input="mark" />
                <div v-if="d.source === 'inferred' && d.inference_chain" class="chain-mini">{{ d.inference_chain.join(' → ') }}</div>
                <el-checkbox v-if="d.source === 'inferred'" v-model="d.confirmed" :disabled="d.value === null || d.value === undefined" size="small" :data-testid="'confirm-' + d.id" @change="mark" @click.stop>
                  我已确认这条推断（含方向与幅度）
                </el-checkbox>
              </td>
              <td><el-button size="small" text type="danger" @click.stop="removeDelta(i)">删除</el-button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- s -->
    <section class="card card-pad">
      <div class="card-title">结构修改 s
        <el-select placeholder="+ 添加算子" size="small" style="width: 220px" data-testid="add-operator" @change="addOperator($event as string)" :model-value="''">
          <el-option v-for="(o, k) in ops" :key="k" :value="k as string" :label="`${o.name}（${kindLabel[o.kind]}）`" />
        </el-select>
      </div>
      <div v-if="!local.structural.length" class="sub">没有结构修改（只用基础模型）。</div>
      <div class="ops">
        <div
          v-for="(s, i) in local.structural" :key="s.id" class="op card" :class="{ 'custom-row': !!s.custom_code || !ops[s.op_id], focus: itemHighlight(s.id) }"
          :data-item="s.id" @click="focusItem(s.id)"
        >
          <div class="row">
            <b class="mono">{{ s.id }}</b>
            <span>{{ ops[s.op_id]?.name ?? s.op_id }}</span>
            <el-tag size="small" effect="plain">{{ kindLabel[s.kind] }}</el-tag>
            <el-tag v-if="s.custom_code || !ops[s.op_id]" size="small" type="warning">custom 待审</el-tag>
            <span class="grow" />
            <el-button size="small" text type="danger" @click.stop="removeOperator(i)">删除</el-button>
          </div>
          <div v-if="ops[s.op_id]" class="sub">{{ ops[s.op_id].meaning }}</div>
          <div class="params">
            <label v-for="(def, k) in ops[s.op_id]?.params ?? {}" :key="k" :class="{ bad: paramError(s, k as string) }">
              <span>{{ def.label }}</span>
              <el-input v-if="def.type === 'list_branch'" size="small" :model-value="branchesText(s)" placeholder="L428,L429" :data-testid="`param-${s.id}-${k}`" @update:model-value="(v: string) => setBranches(s, v)" />
              <el-select v-else-if="def.choices" size="small" :model-value="s.params[k as string]" @update:model-value="(v: any) => setParam(s, k as string, v)">
                <el-option v-for="c in def.choices" :key="c" :value="c" :label="c" />
              </el-select>
              <el-input-number
                v-else size="small" :controls="false" :model-value="numVal(s.params[k as string])" :precision="def.type === 'int' ? 0 : 4" :min="def.type === 'int' ? 1 : 0"
                :placeholder="def.nullable ? '留空用默认值' : '必填'" :data-testid="`param-${s.id}-${k}`"
                @update:model-value="(v: number | undefined) => setParam(s, k as string, v ?? null)"
              />
              <em v-if="k === 'beta' && (s.params.beta === null || s.params.beta === undefined)" class="lv-warn">β 为空：用配置默认值并告警</em>
            </label>
          </div>
          <details v-if="s.custom_code" class="customcode"><summary>custom_code（大模型写的新算子，待人工审核）</summary><pre>{{ s.custom_code }}</pre></details>
        </div>
      </div>
    </section>

    <!-- R -->
    <section class="card card-pad">
      <div class="card-title">求解要求 R </div>
      <div class="omega">
        <label>求解器
          <el-select v-model="local.solver_req.solver" size="small" @change="mark">
            <el-option value="builtin" label="内置求解器（HiGHS · 直流近似 OTS）" /><el-option value="mock" label="mock（占位）" /><el-option value="ipopt" label="IPOPT" /><el-option value="copt" label="COPT" /><el-option value="gurobi" label="Gurobi" /><el-option value="external" label="外部命令" />
          </el-select>
        </label>
        <label>时限（秒）<el-input-number v-model="local.solver_req.time_limit_s" size="small" :min="1" :controls="false" @change="mark" /></label>
        <label>容差<el-input-number v-model="local.solver_req.tolerance" size="small" :controls="false" :precision="8" :step="1e-6" @change="mark" /></label>
        <label>输出项
          <el-select v-model="local.solver_req.outputs" multiple size="small" @change="mark">
            <el-option v-for="o in ['branch_status', 'gen_p', 'bus_vm', 'branch_flow']" :key="o" :value="o" :label="o" />
          </el-select>
        </label>
      </div>
    </section>

    <!-- 底部 -->
    <section class="card card-pad footer" data-testid="spec-footer">
      <div class="scale" data-testid="scale-summary">
        <div class="sub">变量与约束规模（完整 {{ scale?.T ?? local.omega.periods }} 时段，按模板逐块计数）</div>
        <template v-if="scale">
          <div class="nums">
            <span>变量 <b>{{ fmt(scale.vars_total) }}</b></span>
            <span>其中 0-1 变量 <b data-testid="scale-binary">{{ fmt(scale.vars_binary) }}</b></span>
            <span>约束 <b>{{ fmt(scale.constraints) }}</b></span>
            <span class="sub">（B9 按事故集展开，由求解链决定，未计入）</span>
          </div>
          <div class="rules" data-testid="scale-rules">
            <span class="sub">开断变量数（三种可开断集合口径并列）：</span>
            <span v-for="(r, k) in scale.by_rule" :key="k" class="rule" :class="{ cur: r.current }" :data-rule="k">
              {{ r.name }} <b>{{ fmt(r.binary_vars) }}</b><i v-if="r.current">当前</i>
            </span>
          </div>
        </template>
        <div v-else class="sub">规模估算将在规格就绪后显示</div>
      </div>
      <div v-if="blockers.length" class="blockers" data-testid="blockers">
        <div v-for="b in blockers" :key="b" class="lv-warn">· {{ b }}</div>
      </div>
      <div class="row actions">
        <el-button :disabled="!dirty || t.busy" data-testid="save-spec" @click="save">保存修改</el-button>
        <el-button :disabled="t.busy" data-testid="back-btn" @click="back">退回修改</el-button>
        <span class="grow" />
        <el-tooltip :disabled="canConfirm && !dirty" :content="blockers[0] ?? ''" placement="top">
          <span>
            <el-button type="primary" :disabled="!canConfirm" :loading="t.busy" data-testid="confirm-btn" @click="confirmClick">
              确认并生成代码
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </section>

    <el-dialog v-model="reasonDlg" title="写明本版改动原因" width="440px" append-to-body>
      <p class="sub">将生成 v{{ (t.current ?? 0) + 1 }}（父版本 v{{ t.current }}），原因会写进版本链。留空则自动列出改动。</p>
      <el-input v-model="reason" type="textarea" :rows="3" placeholder="例如：用户确认限额下降幅度为 20%" data-testid="reason-input" />
      <template #footer>
        <el-button @click="reasonDlg = false">取消</el-button>
        <el-button type="primary" data-testid="reason-ok" @click="confirmWithReason">确认并生成</el-button>
      </template>
    </el-dialog>
  </div>
  <div v-else class="empty sub">先在左栏输入指令并解析，这里会出现可编辑的规格。</div>
</template>

<style scoped>
.spec { display: flex; flex-direction: column; gap: var(--sp-3); }
.omega { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: var(--sp-3); }
.omega label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-xs); color: var(--c-muted); }
.scroll-x { overflow-x: auto; }
.dp td { vertical-align: top; }
.dp tr.focus td { box-shadow: inset 0 0 0 2px var(--c-primary); }
.dp tr.infer-row td { border-bottom-color: var(--c-infer-line); }
.ev { min-width: 200px; }
.chain-mini { font-size: var(--fs-xs); color: var(--c-infer); margin: 2px 0; }
.tiny { font-size: 11px; }
.ops { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: var(--sp-3); }
.op { padding: var(--sp-3); display: flex; flex-direction: column; gap: 6px; }
.op.focus { box-shadow: 0 0 0 2px var(--c-primary); }
.params { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.params label { display: flex; flex-direction: column; gap: 3px; font-size: var(--fs-xs); color: var(--c-muted); }
.params label.bad span { color: var(--c-danger); }
.customcode pre { background: var(--c-custom); padding: 8px; border-radius: var(--radius-sm); overflow: auto; font-size: var(--fs-xs); }
.footer { position: sticky; bottom: 0; z-index: 3; }
.nums { display: flex; flex-wrap: wrap; gap: 16px; margin: 4px 0; font-size: var(--fs-md); }
.rules { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.rule { border: 1px solid var(--c-hairline); border-radius: 12px; padding: 1px 10px; font-size: var(--fs-xs); background: var(--c-surface-2); }
.rule.cur { border-color: var(--c-primary); background: var(--c-primary-bg); }
.rule i { font-style: normal; color: var(--c-primary); margin-left: 6px; }
.blockers { margin: 8px 0; font-size: var(--fs-sm); }
.actions { margin-top: 8px; }
.empty { padding: var(--sp-5); border: 1px dashed var(--c-border); border-radius: var(--radius); }
</style>
