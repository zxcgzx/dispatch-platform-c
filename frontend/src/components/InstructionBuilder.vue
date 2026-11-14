<script setup lang="ts">
// 指令构建器：不用手打，选“对象 → 动作 → 幅度 → 附加要求”，自动拼成一句调度指令填入输入框；仍可手改。
// 拼出的句式都是演示引擎能直接解析的写法。
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'

const emit = defineEmits<{ (e: 'apply', text: string, send: boolean): void }>()

type Obj = { id: string; label: string; meshed?: boolean }
const objects = ref<{ bus: Obj[]; branch: Obj[]; gen: Obj[] }>({ bus: [], branch: [], gen: [] })
const loaded = ref(false)

// 常用对象（真实数据里负载较重 / 位置关键的对象），没加载完整列表前也能直接点
const quick = {
  bus: [{ id: 'B43', label: 'B43（110kV）' }, { id: 'B28', label: 'B28（220kV）' }, { id: 'B196', label: 'B196（500kV）' }, { id: 'B172', label: 'B172（220kV）' }],
  branch: [{ id: 'L875', label: 'L875（176–1309，500kV）' }, { id: 'L583', label: 'L583（1257–25，220kV）' }, { id: 'L155', label: 'L155（174–172，220kV）' }, { id: 'L376', label: 'L376（54–359，110kV）' }],
  gen: [{ id: 'G237', label: 'G237（母线 314）' }, { id: 'G233', label: 'G233（母线 175）' }, { id: 'G143', label: 'G143（母线 919）' }],
}

const kind = ref<'bus' | 'branch' | 'gen'>('branch')
const target = ref('')
const action = ref('')
const amount = ref<number | null>(null)
const nMinus1 = ref(false)
const fewSwitch = ref(false)
const swLimit = ref<number | null>(null)
const goals = ref<string[]>([])
const ucLimit = ref<number | null>(null)
const goalOpts = [
  { v: 'econ', label: '经济性', text: '考虑发电成本' },
  { v: 'rel', label: '可靠性', text: '考虑可靠性' },
  { v: 'ren', label: '新能源消纳', text: '考虑新能源消纳' },
  { v: 'loss', label: '网损最小', text: '网损尽量小' },
  { v: 'volt', label: '电压偏差', text: '考虑电压偏差' },
  { v: 'redis', label: '机组出力调整', text: '机组出力调整' },
]

// 动作模板：text 里的 {o} 是对象，{n} 是数值
const actions: Record<string, { key: string; label: string; tpl: string; unit?: string; need?: boolean; def?: number }[]> = {
  bus: [
    { key: 'pd_up', label: '有功负荷提高', tpl: '{o} 的有功负荷提高 {n}%', unit: '%', need: true, def: 20 },
    { key: 'pd_down', label: '有功负荷降低', tpl: '{o} 的有功负荷降低 {n}%', unit: '%', need: true, def: 10 },
    { key: 'pd_add', label: '有功负荷增加', tpl: '{o} 的有功负荷增加 {n} MW', unit: 'MW', need: true, def: 30 },
    { key: 'vmax', label: '电压上限设为', tpl: '{o} 的电压上限设为 {n}', unit: 'p.u.', need: true, def: 1.07 },
  ],
  branch: [
    { key: 'outage', label: '检修停运', tpl: '{o} 检修停运' },
    { key: 'heat', label: '高温，热稳限额下降（幅度另问）', tpl: '持续高温，{o} 热稳限额下降' },
    { key: 'rate_down', label: '热稳限额降低', tpl: '{o} 热稳限额降低 {n}%', unit: '%', need: true, def: 30 },
    { key: 'rate_set', label: '热稳限额设为', tpl: '{o} 热稳限额设为 {n} MVA', unit: 'MVA', need: true, def: 300 },
  ],
  gen: [
    { key: 'limit', label: '出力受限（幅度另问）', tpl: '{o} 近期出力受限' },
    { key: 'pmax_down', label: '出力上限降低', tpl: '{o} 的出力上限降低 {n}%', unit: '%', need: true, def: 20 },
    { key: 'outage', label: '检修停运', tpl: '{o} 检修停运' },
  ],
}
const kindLabel = { bus: '母线', branch: '线路', gen: '机组' }
const list = computed(() => {
  const full = objects.value[kind.value]
  return full.length ? full : quick[kind.value]
})
const act = computed(() => actions[kind.value].find((a) => a.key === action.value))

watch(kind, () => { target.value = ''; action.value = ''; amount.value = null })
watch(action, () => { if (act.value?.def !== undefined) amount.value = act.value.def; else amount.value = null })

async function loadAll() {            // 第一次展开下拉时再加载完整对象表
  if (loaded.value) return
  loaded.value = true
  try { objects.value = await api.get('/objects') } catch { loaded.value = false }
}
onMounted(() => { void 0 })

const objText = computed(() => {                // 母线写“母线 43”，线路 / 机组直接用编号
  const id = target.value.trim().toUpperCase()
  if (!id) return ''
  return kind.value === 'bus' && /^B\d+$/.test(id) ? '母线 ' + id.slice(1) : id
})
const finalText = computed(() => {
  const parts: string[] = []
  const a = act.value
  if (a && objText.value && (!a.need || amount.value !== null)) {
    parts.push(a.tpl.replace('{o}', objText.value).replace('{n}', String(amount.value ?? '')))
  }
  if (nMinus1.value) parts.push('要求满足 N−1')
  if (fewSwitch.value) parts.push('尽量少动开关')
  if (swLimit.value) parts.push(`开关操作不超过 ${swLimit.value} 次`)
  if (ucLimit.value) parts.push(`机组启停不超过 ${ucLimit.value} 次`)
  goalOpts.filter((g) => goals.value.includes(g.v)).forEach((g) => parts.push(g.text))
  return parts.length ? parts.join('，') + '。' : ''
})
const needAmount = computed(() => !!act.value?.need)
const ready = computed(() => !!finalText.value)

function apply(send: boolean) {
  if (!finalText.value) return
  emit('apply', finalText.value, send)
}
function reset() {
  target.value = ''; action.value = ''; amount.value = null; nMinus1.value = false; fewSwitch.value = false; swLimit.value = null; goals.value = []; ucLimit.value = null
}
</script>

<template>
  <div class="ib" data-testid="builder">
    <div class="row1">
      <span class="lab">1 对象</span>
      <el-radio-group v-model="kind" size="small" data-testid="b-kind">
        <el-radio-button value="branch">线路</el-radio-button>
        <el-radio-button value="bus">母线</el-radio-button>
        <el-radio-button value="gen">机组</el-radio-button>
      </el-radio-group>
      <el-select v-model="target" size="small" filterable allow-create default-first-option :placeholder="`选择或搜索${kindLabel[kind]}（如 ${kind === 'bus' ? 'B43' : kind === 'branch' ? 'L875' : 'G237'}）`" style="width: 270px" data-testid="b-target" @visible-change="(v: boolean) => v && loadAll()">
        <el-option-group label="常用">
          <el-option v-for="o in quick[kind]" :key="'q' + o.id" :value="o.id" :label="o.label" />
        </el-option-group>
        <el-option-group v-if="objects[kind].length" :label="`全部 ${kindLabel[kind]}`">
          <el-option v-for="o in objects[kind]" :key="o.id" :value="o.id" :label="o.label" />
        </el-option-group>
      </el-select>
    </div>
    <div class="row1">
      <span class="lab">2 动作</span>
      <div class="chips" data-testid="b-actions">
        <button v-for="a in actions[kind]" :key="a.key" class="chip" :class="{ on: action === a.key }" :data-action="a.key" @click="action = a.key">{{ a.label }}</button>
      </div>
      <template v-if="needAmount">
        <el-input-number v-model="amount" size="small" :controls="false" style="width: 90px" :step="1" data-testid="b-amount" />
        <span class="unit">{{ act?.unit }}</span>
      </template>
    </div>
    <div class="row1">
      <span class="lab">3 附加要求</span>
      <el-checkbox v-model="nMinus1" size="small" data-testid="b-n1">满足 N−1</el-checkbox>
      <el-checkbox v-model="fewSwitch" size="small" data-testid="b-few">尽量少动开关</el-checkbox>
      <span class="sw">开关操作不超过
        <el-select v-model="swLimit" size="small" clearable placeholder="不限" style="width: 76px" data-testid="b-swlimit"><el-option v-for="k in [1, 2, 3, 5]" :key="k" :value="k" :label="`${k} 次`" /></el-select></span>
    </div>
    <div class="row1">
      <span class="lab">4 目标与机组</span>
      <el-checkbox-group v-model="goals" size="small" data-testid="b-goals">
        <el-checkbox v-for="g in goalOpts" :key="g.v" :value="g.v" :data-goal="g.v">{{ g.label }}</el-checkbox>
      </el-checkbox-group>
      <span class="sw">机组启停不超过
        <el-select v-model="ucLimit" size="small" clearable placeholder="不启停" style="width: 86px" data-testid="b-uclimit"><el-option v-for="k in [1, 2, 3, 5]" :key="k" :value="k" :label="`${k} 次`" /></el-select></span>
    </div>
    <div class="out">
      <div class="prev" :class="{ empty: !ready }" data-testid="b-preview">
        <span v-if="ready">{{ finalText }}</span>
        <span v-else>选好对象和动作，这里会生成一句调度指令（也可以只勾“附加要求”）</span>
      </div>
      <el-button size="small" :disabled="!ready" data-testid="b-fill" @click="apply(false)">填入输入框</el-button>
      <el-button size="small" type="primary" :disabled="!ready" data-testid="b-run" @click="apply(true)">生成并解析</el-button>
      <el-button size="small" text @click="reset">清空</el-button>
    </div>
  </div>
</template>

<style scoped>
.ib { background: var(--c-surface); border: 1px solid var(--c-hairline); border-radius: 12px; padding: 12px 16px; display: flex; flex-direction: column; gap: 9px; box-shadow: var(--shadow); }
.row1 { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.lab { width: 72px; font-size: 12.5px; color: var(--c-muted); font-weight: 600; flex: none; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font: inherit; font-size: 12.5px; padding: 4px 12px; border-radius: 14px; border: 1px solid var(--c-border); background: var(--c-surface); cursor: pointer; transition: all 0.12s; }
.chip:hover { border-color: var(--c-primary); color: var(--c-primary); }
.chip.on { background: var(--c-primary); border-color: var(--c-primary); color: #fff; }
.unit { font-size: 12px; color: var(--c-muted); }
.sw { font-size: 12.5px; color: var(--c-ink); display: inline-flex; align-items: center; gap: 6px; }
.out { display: flex; align-items: center; gap: 8px; padding-top: 9px; border-top: 1px dashed var(--c-hairline); }
.prev { flex: 1; background: var(--c-primary-bg); color: var(--c-primary-ink); border-radius: 8px; padding: 7px 12px; font-size: 13.5px; font-weight: 500; min-height: 34px; display: flex; align-items: center; }
.prev.empty { background: var(--c-surface-2); color: var(--c-faint); font-weight: 400; font-size: 12.5px; }
</style>
