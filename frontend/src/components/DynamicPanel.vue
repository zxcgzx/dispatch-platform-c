<script setup lang="ts">
// 动态建模：不重新输入指令，直接切换优化类型、叠加机组建模与目标项，规格随之更新；
// 外部动态建模方法（多场景优化规则 → 建模逻辑 → 结果验证）接入后在下方三段展示。
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'
import type { ModelSpec } from '@/types/api'

const t = useTaskStore()
const spec = computed(() => t.spec)
const ops = computed(() => t.meta?.operators ?? {})
const has = (id: string) => !!spec.value?.structural.some((s) => s.op_id === id)

const problem = computed({
  get: () => spec.value?.omega.problem ?? 'multi_period_ac_ots',
  set: (v: string) => edit((s) => { s.omega.problem = v as any }),
})

const stackable = [
  { id: 'generator_redispatch', group: '机组建模', hint: '出力作为决策变量，可限爬坡' },
  { id: 'unit_commitment', group: '机组建模', hint: '启停作为 0-1 变量，限制总次数' },
  { id: 'loss_min', group: '目标函数', hint: '网损' },
  { id: 'voltage_deviation', group: '目标函数', hint: '电压偏差' },
  { id: 'cost_economic', group: '目标函数', hint: '经济性（需要给出单价）' },
  { id: 'reliability_nm1', group: '目标函数', hint: '可靠性（需要给出失负荷代价）' },
  { id: 'renewable_accommodation', group: '目标函数', hint: '新能源消纳（需要给出弃电惩罚）' },
]

async function edit(fn: (s: ModelSpec) => void) {
  if (!spec.value) return
  const s = JSON.parse(JSON.stringify(spec.value)) as ModelSpec
  fn(s)
  await t.saveSpec(s)
}
async function toggle(id: string, on: boolean) {
  await edit((s) => {
    if (on) {
      const o = ops.value[id]
      const n = Math.max(0, ...s.structural.map((x) => +x.id.split('-')[1] || 0)) + 1
      const params: Record<string, any> = {}
      Object.entries(o.params).forEach(([k, d]: [string, any]) => { params[k] = d.default ?? null })
      s.structural.push({ id: `s-${n}`, kind: o.kind as any, op_id: id, params, source: 'explicit', evidence: '', custom_code: null, origin: null,
        pending_fields: Object.keys(params).filter((k) => params[k] === null && !o.params[k].nullable) } as any)
    } else s.structural = s.structural.filter((x) => x.op_id !== id)
  })
  ElMessage.success(on ? '已加入，请在“规格”里补全需要填写的参数' : '已去掉')
}
const groups = computed(() => ['机组建模', '目标函数'].map((g) => ({ g, items: stackable.filter((x) => x.group === g) })))
const stages = [
  { n: '1', t: '多场景优化规则', d: '按场景选择优化类型与约束集合，输出规则表。' },
  { n: '2', t: '建模逻辑', d: '把规则落成规格 Δπ / s，说明每一步为什么这样建。' },
  { n: '3', t: '结果验证', d: '对求解结果做回代校验，对照指令要求逐条核对。' },
]
</script>

<template>
  <div class="dp" data-testid="dynamic-panel">
    <section class="card card-pad">
      <div class="card-title">优化类型 <span class="sub">随时切换，规格、公式、代码、规模同步更新</span></div>
      <el-radio-group v-model="problem" data-testid="dyn-problem">
        <el-radio-button value="multi_period_ac_ots">AC-OTS（含拓扑重构）</el-radio-button>
        <el-radio-button value="multi_period_acopf">AC-OPF（固定拓扑）</el-radio-button>
      </el-radio-group>
    </section>

    <section v-for="g in groups" :key="g.g" class="card card-pad">
      <div class="card-title">{{ g.g }} <span class="sub">可叠加、可组合</span></div>
      <div class="opts">
        <label v-for="x in g.items" :key="x.id" class="opt" :class="{ on: has(x.id) }">
          <el-checkbox :model-value="has(x.id)" :data-op="x.id" @change="(v: any) => toggle(x.id, !!v)">{{ ops[x.id]?.name ?? x.id }}</el-checkbox>
          <span class="sub">{{ x.hint }}</span>
        </label>
      </div>
    </section>

    <section class="card card-pad">
      <div class="card-title">动态建模方法 <StatusBadge feature="m3.ext_dynamic" /></div>
      <div class="stages">
        <div v-for="s in stages" :key="s.n" class="stage"><i>{{ s.n }}</i><div><b>{{ s.t }}</b><div class="sub">{{ s.d }}</div></div></div>
      </div>
      <p class="sub">配置 <code>METHOD_ENDPOINT</code> 后，三段结果在这里展示；未配置时由内置规则引擎完成指令 → 规格这一步。</p>
    </section>
  </div>
</template>

<style scoped>
.dp { display: flex; flex-direction: column; gap: var(--sp-3); }
.opts { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px; }
.opt { border: 1px solid var(--c-hairline); border-radius: var(--radius); padding: 8px 12px; display: flex; flex-direction: column; gap: 2px; background: var(--c-surface); }
.opt.on { border-color: var(--c-primary); background: var(--c-primary-bg); }
.stages { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 8px; }
.stage { display: flex; gap: 10px; align-items: flex-start; border: 1px dashed var(--c-border); border-radius: var(--radius); padding: 10px 12px; }
.stage i { width: 24px; height: 24px; border-radius: 50%; background: var(--c-primary-bg); color: var(--c-primary-ink); display: grid; place-items: center; font-style: normal; font-weight: 700; flex: none; }
</style>
