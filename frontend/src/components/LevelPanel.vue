<script setup lang="ts">
// 步骤 2（层级判定）：解析卡片（点实体 → 在指令原文里高亮对应 evidence）、L1–L4 四宫格（高亮程序判出的一格，可人工改选并填写原因）、推断链。
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import type { Entity } from '@/types/api'

const t = useTaskStore()
const parse = computed(() => t.parse)
const level = computed(() => t.levelInfo)
const spec = computed(() => t.spec)
const activeEntity = ref<string | null>(null)

const typeLabel: Record<string, string> = { bus: '母线', branch: '支路', gen: '机组', period: '时段', kv: '电压等级', keyword: '要求' }
const roleLabel: Record<string, string> = { inference: '推断触发词', outage: '检修停运', n1: 'N−1', structural: '结构要求', magnitude: '数值' }
const statusLabel: Record<string, string> = { found: '已确定', not_found: '对象不存在', ambiguous: '需追问', ok: '已识别', fuzzy: '模糊，需追问' }

// ---- 原文高亮：把指令按实体 / evidence 切段
const hlIds = computed(() => {
  const ent = parse.value?.entities.find((e) => e.id === activeEntity.value)
  return ent ? ent.item_ids : []
})
const segments = computed(() => {
  const text = parse.value?.instruction ?? ''
  const p = parse.value
  if (!text || !p) return [{ text, hl: false, ent: false }]
  const marks: { s: number; e: number; kind: 'ev' | 'ent' }[] = []
  const act = p.entities.find((e) => e.id === activeEntity.value)
  if (act) {
    marks.push({ s: act.start, e: act.end, kind: 'ent' })
    for (const id of act.item_ids) {
      const sp = p.evidence_spans[id]
      if (sp) marks.push({ s: sp[0], e: sp[1], kind: 'ev' })
    }
  }
  const cuts = new Set<number>([0, text.length])
  marks.forEach((m) => {
    cuts.add(m.s)
    cuts.add(m.e)
  })
  const pts = [...cuts].sort((a, b) => a - b)
  const out: { text: string; hl: boolean; ent: boolean }[] = []
  for (let i = 0; i < pts.length - 1; i++) {
    const [s, e] = [pts[i], pts[i + 1]]
    if (s === e) continue
    out.push({
      text: text.slice(s, e),
      hl: marks.some((m) => m.kind === 'ev' && m.s <= s && e <= m.e),
      ent: marks.some((m) => m.kind === 'ent' && m.s <= s && e <= m.e),
    })
  }
  return out
})
function chipTitle(e: Entity) {
  if (e.type === 'period') return e.periods === null ? '模糊时间说法' : e.periods.length ? `时段 ${e.periods[0]}–${e.periods.at(-1)}` : '全部时段'
  if (e.type === 'kv') return `${e.kv}kV`
  return e.object_id ?? e.text
}
function click(e: Entity) {
  activeEntity.value = activeEntity.value === e.id ? null : e.id
  if (e.item_ids.length) t.setFocus(e.item_ids[0], 'entity')
}

// ---- 四宫格
const cells = [
  { l: 'L1', row: '明确', col: '仅改参数' },
  { l: 'L2', row: '推断', col: '仅改参数' },
  { l: 'L3', row: '明确', col: '改结构' },
  { l: 'L4', row: '推断', col: '改结构' },
]
const ruleText: Record<string, string> = {
  L1: '参数明确 · 不改结构', L2: '含推断参数 · 不改结构', L3: '参数明确 · 改结构', L4: '含推断参数 · 改结构',
}
const overriding = ref(false)
const overrideLevel = ref('L1')
const overrideReason = ref('')
function openOverride(l: string) {
  overrideLevel.value = l
  overrideReason.value = spec.value?.level_override?.reason ?? ''
  overriding.value = true
}
async function applyOverride() {
  if (!spec.value) return
  if (!overrideReason.value.trim()) return ElMessage.warning('请填写改选原因')
  const s = JSON.parse(JSON.stringify(spec.value))
  s.level_override = overrideLevel.value === level.value?.level ? null : { level: overrideLevel.value, reason: overrideReason.value.trim() }
  await t.saveSpec(s)
  overriding.value = false
}
async function clearOverride() {
  if (!spec.value) return
  const s = JSON.parse(JSON.stringify(spec.value))
  s.level_override = null
  await t.saveSpec(s)
}

const inferred = computed(() => (spec.value?.delta_pi ?? []).filter((d) => d.source === 'inferred'))
const pending = computed(() => parse.value?.pending ?? [])
</script>

<template>
  <div class="lp" data-testid="level-panel">
    <section class="card card-pad">
      <div class="card-title">解析卡片 <span class="sub">点一下实体，在指令原文里高亮对应依据</span></div>
      <div v-if="parse" class="orig" data-testid="instruction-view">
        <template v-for="(s, i) in segments" :key="i">
          <mark v-if="s.hl || s.ent" class="hl" :class="{ 'hl-ent': s.ent && !s.hl }" :data-hl="s.hl ? 'ev' : 'ent'">{{ s.text }}</mark>
          <template v-else>{{ s.text }}</template>
        </template>
      </div>
      <div v-if="parse" class="chips">
        <button
          v-for="e in parse.entities" :key="e.id" class="chip" :class="[e.status, { on: activeEntity === e.id }]" :data-entity="e.type" :data-status="e.status"
          :title="e.note ?? ''" @click="click(e)"
        >
          <span class="ty">{{ e.type === 'keyword' ? (roleLabel[e.role ?? ''] ?? '要求') : typeLabel[e.type] }}</span>
          <b>{{ chipTitle(e) }}</b>
          <span class="st">{{ statusLabel[e.status] }}</span>
        </button>
        <span v-if="!parse.entities.length" class="sub">没有识别到对象或要求</span>
      </div>
      <ul v-if="parse?.entities.some((e) => e.note)" class="notes">
        <li v-for="e in parse.entities.filter((x) => x.note)" :key="e.id" :class="e.status === 'not_found' ? 'lv-error' : 'lv-warn'">{{ e.text }}：{{ e.note }}</li>
      </ul>
      <div v-if="parse?.omega_confirm?.evidence" class="n1 sub">
        ω 确认项：<b>N−1 = {{ parse.omega_confirm.n_minus_1 ? '开启' : '关闭' }}</b>（依据“{{ parse.omega_confirm.evidence }}”；这是对基础模型的确认，不算结构修改）
      </div>
      <div v-if="pending.length" class="pend">
        <div v-for="p in pending" :key="p.id" class="lv-warn">“{{ p.evidence }}”：没有明确对象，已挂起，等你指明（系统不会猜）。</div>
      </div>
    </section>

    <section class="card card-pad">
      <div class="card-title">
        层级判定
        <el-tag v-if="level" size="large" :type="level.level === '待追问' ? 'info' : 'primary'" data-testid="level-tag">{{ level.display }}</el-tag>
        <el-tag v-if="level?.overridden" type="warning" effect="plain" size="small">人工改选（程序判级：{{ level.level }}）</el-tag>
      </div>
      <div class="grid" data-testid="level-grid">
        <div class="axis-top"><span /><span>仅改参数</span><span>改结构</span></div>
        <div class="axis-row">
          <div class="rl">明确</div>
          <div class="rl">推断</div>
        </div>
        <div class="cells">
          <button
            v-for="c in cells" :key="c.l" class="cell" :class="{ prog: level?.level === c.l, shown: level?.display === c.l && level?.overridden }"
            :data-level="c.l" :data-active="level?.level === c.l" @click="spec && openOverride(c.l)"
          >
            <b>{{ c.l }}</b><span>{{ ruleText[c.l] }}</span>
            <i v-if="level?.level === c.l" class="badge-p">程序判定</i>
            <i v-if="level?.overridden && level?.display === c.l" class="badge-o">人工改选</i>
          </button>
        </div>
      </div>
      <p class="reason" data-testid="level-reason">{{ level?.text ?? '尚未解析' }}</p>
      <p v-if="level?.level === '待追问'" class="lv-warn">没有任何参数修改或结构修改：层级为“待追问”，请回答追问或补充条件。</p>
      <div v-if="level?.overridden" class="row" style="gap: 8px">
        <span class="sub">改选原因：{{ spec?.level_override?.reason }}</span>
        <el-button size="small" text type="primary" @click="clearOverride">取消改选</el-button>
      </div>
      <p class="sub" style="margin-top: 4px">点四宫格里的任一格可人工改选并填写原因；改选只覆盖显示，程序判级另存，测评模式按程序判级统计。</p>
    </section>

    <section v-if="inferred.length" class="card card-pad infer-box" data-testid="infer-chain">
      <div class="card-title">推断链 <span class="infer-tag">推断项</span><span class="sub">事件 → 机理 → 参数；推断出的方向和幅度必须由你确认</span></div>
      <div v-for="d in inferred" :key="d.id" class="chain">
        <div class="sub"><b>{{ d.id }}</b> {{ d.target }}.{{ d.param }}</div>
        <div class="steps">
          <template v-for="(s, i) in d.inference_chain ?? []" :key="i">
            <span class="node">{{ s }}</span><span v-if="i < (d.inference_chain?.length ?? 0) - 1" class="arrow">→</span>
          </template>
        </div>
        <div class="sub">幅度：<b>{{ d.value === null ? '待确认' : d.value }}</b> · {{ d.confirmed ? '已确认' : '尚未确认' }}</div>
      </div>
    </section>

    <el-dialog v-model="overriding" title="人工改选层级" width="420px" append-to-body>
      <p class="sub">程序判级：{{ level?.level }}。改选只覆盖显示的层级，程序判级会保留，测评模式按程序判级统计。</p>
      <el-radio-group v-model="overrideLevel"><el-radio v-for="c in cells" :key="c.l" :value="c.l">{{ c.l }}</el-radio></el-radio-group>
      <el-input v-model="overrideReason" type="textarea" :rows="3" placeholder="改选原因（必填）" style="margin-top: 12px" data-testid="override-reason" />
      <template #footer>
        <el-button @click="overriding = false">取消</el-button>
        <el-button type="primary" data-testid="override-ok" @click="applyOverride">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.lp { display: flex; flex-direction: column; gap: var(--sp-3); }
.orig { background: var(--c-surface-2); border-radius: var(--radius); padding: 10px 12px; line-height: 1.9; font-size: var(--fs-md); margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font: inherit; font-size: var(--fs-xs); border: 1px solid var(--c-border); background: var(--c-surface); border-radius: 14px; padding: 2px 10px; cursor: pointer; display: inline-flex; gap: 6px; align-items: center; }
.chip .ty { color: var(--c-muted); }
.chip .st { color: var(--c-faint); }
.chip.on { border-color: var(--c-primary); background: var(--c-primary-bg); }
.chip.not_found { border-color: var(--c-danger); color: var(--c-danger); background: var(--c-danger-bg); }
.chip.ambiguous, .chip.fuzzy { border-color: var(--c-infer-line); background: var(--c-infer-bg); }
.notes { margin: 8px 0 0; padding-left: 18px; font-size: var(--fs-xs); }
.n1, .pend { margin-top: 8px; font-size: var(--fs-sm); }
.grid { display: grid; grid-template-columns: 56px 1fr; grid-template-rows: auto auto; gap: 4px 8px; max-width: 520px; }
.axis-top { grid-column: 2; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: var(--fs-xs); color: var(--c-muted); text-align: center; }
.axis-top span:first-child { display: none; }
.axis-top span:nth-child(2) { grid-column: 1; } .axis-top span:nth-child(3) { grid-column: 2; }
.axis-row { display: grid; grid-template-rows: 1fr 1fr; gap: 8px; }
.rl { display: grid; place-items: center; font-size: var(--fs-xs); color: var(--c-muted); }
.cells { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.cell { position: relative; font: inherit; border: 1.25px solid var(--c-border); border-radius: var(--radius); background: var(--c-surface); padding: 12px 8px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 2px; min-height: 66px; }
.cell b { font-size: var(--fs-xl); }
.cell span { font-size: var(--fs-xs); color: var(--c-muted); }
.cell:hover { border-color: var(--c-primary); }
.cell.prog { background: var(--c-primary-bg); border: 2px solid var(--c-primary); }
.cell.shown { outline: 2px dashed var(--c-infer-line); outline-offset: 2px; }
.badge-p, .badge-o { position: absolute; top: 4px; right: 6px; font-style: normal; font-size: 10px; color: var(--c-primary-ink); }
.badge-o { top: auto; bottom: 4px; color: var(--c-infer); }
.reason { margin: 10px 0 4px; font-size: var(--fs-sm); }
.infer-box { background: var(--c-infer-bg); border-color: var(--c-infer-line); }
.chain { margin-bottom: 8px; }
.steps { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 4px 0; }
.node { background: var(--c-surface); border: 1px solid var(--c-infer-line); border-radius: var(--radius-sm); padding: 2px 10px; font-size: var(--fs-sm); }
.arrow { color: var(--c-infer); }
</style>
