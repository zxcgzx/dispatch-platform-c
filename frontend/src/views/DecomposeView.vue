<script setup lang="ts">
// 聚合与分解：问题类型识别、节点聚合、时空聚合、按县域分区与联络线。多智能体协同求解待开发。
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'

const t = useTaskStore()
const part = ref<any>(null)
const task = ref<any>(null)
const err = ref('')
const groupT = ref(4)

onMounted(async () => {
  try {
    part.value = await api.get('/decompose/partition')
    if (t.taskId && t.current !== null) task.value = await api.get(`/tasks/${t.taskId}/decompose?version=${t.viewVersion ?? t.current}`)
  } catch (e: any) { err.value = e?.message || '加载失败' }
})
const maxBuses = computed(() => Math.max(1, ...(part.value?.regions ?? []).map((r: any) => r.buses)))
const groups = computed(() => {
  const T = part.value?.time_aggregation.periods ?? 1
  const out: number[][] = []
  for (let s = 0; s < T; s += groupT.value) out.push(Array.from({ length: Math.min(groupT.value, T - s) }, (_, i) => s + i + 1))
  return out
})
</script>

<template>
  <div class="page">
    <h2>聚合与分解</h2>
    <p class="sub">把 905 节点、1000 支路的大问题拆成可以分别求解的子问题：先识别问题类型，再做节点聚合、时空聚合，最后按县域分区，区域之间的联络线就是子问题的耦合。</p>
    <div v-if="err" class="lv-error">{{ err }}</div>
    <template v-if="part">
      <section v-if="task" class="card card-pad" data-testid="classify-card">
        <div class="card-title">问题类型识别 <StatusBadge feature="m9.classify" small /><span class="sub">来自当前任务 v{{ task.version }}</span></div>
        <div class="tags"><el-tag v-for="x in task.classify.types" :key="x" effect="plain">{{ x }}</el-tag></div>
        <div class="sub">分解策略：<b>{{ task.classify.strategy }}</b></div>
        <div class="sub">{{ task.classify.reason }}</div>
      </section>
      <section v-else class="card card-pad"><div class="card-title">问题类型识别 <StatusBadge feature="m9.classify" small /></div><div class="sub">先在工作台生成一个任务并确认规格，这里会显示它的问题类型与分解策略。</div></section>

      <div class="two">
        <section class="card card-pad" data-testid="node-agg">
          <div class="card-title">节点聚合 <StatusBadge feature="m9.node_agg" small /></div>
          <div class="big">{{ part.node_aggregation.buses }} → {{ part.node_aggregation.after }}</div>
          <div class="sub">{{ part.node_aggregation.note }}（可并入 {{ part.node_aggregation.low_voltage_leaves }} 个）</div>
        </section>
        <section class="card card-pad" data-testid="time-agg">
          <div class="card-title">时空聚合 <StatusBadge feature="m9.time_agg" small /></div>
          <div class="row"><span class="sub">时段方向每</span><el-input-number v-model="groupT" size="small" :min="1" :max="16" style="width: 90px" /><span class="sub">个时段合并为 1 个决策段</span></div>
          <div class="seg"><span v-for="(g, i) in groups" :key="i">{{ g[0] }}{{ g.length > 1 ? '–' + g[g.length - 1] : '' }}</span></div>
          <div class="sub">{{ part.time_aggregation.periods }} 个时段 → {{ groups.length }} 个决策段</div>
        </section>
      </div>

      <section class="card card-pad" data-testid="regions">
        <div class="card-title">区域分解与联络线 <StatusBadge feature="m9.partition" small /><span class="sub">共 {{ part.n_regions }} 个县域，联络线 {{ part.tie_total }} 条</span></div>
        <table class="table-plain">
          <thead><tr><th>区域</th><th style="width: 260px">节点数</th><th>110kV 及以上</th><th>负荷 MW</th><th>机组出力 MW</th><th>联络线</th></tr></thead>
          <tbody>
            <tr v-for="r in part.regions" :key="r.name">
              <td><b>{{ r.name }}</b></td>
              <td><span class="bar" :style="{ width: (r.buses / maxBuses) * 180 + 'px' }" /> {{ r.buses }}</td>
              <td>{{ r.high_voltage_buses }}</td><td>{{ r.load_mw }}</td><td>{{ r.gen_mw }}</td>
              <td>{{ r.tie_count }} <span class="sub mono">{{ r.tie_lines.slice(0, 3).join(' ') }}{{ r.tie_count > 3 ? ' …' : '' }}</span></td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <section class="card card-pad">
      <div class="card-title">待开发</div>
      <div class="cards">
        <div class="ph"><div class="row"><b>知识增强的问题分解</b><StatusBadge feature="m9.knowledge" small /></div><div class="sub">建模规则与调度规程知识库，辅助选择分解策略。</div></div>
        <div class="ph"><div class="row"><b>多智能体协同求解</b><StatusBadge feature="m9.multiagent" small /></div><div class="sub">每个子问题一个智能体，边界信息交换，直到全局收敛。</div></div>
      </div>
    </section>
  </div>
</template>

<style scoped>
section { margin-top: var(--sp-3); }
.tags { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); }
.two section { margin-top: var(--sp-3); }
.big { font-size: 30px; font-weight: 700; color: var(--c-brand-blue); margin: 4px 0; }
.seg { display: flex; gap: 6px; margin: 8px 0; flex-wrap: wrap; }
.seg span { background: var(--c-primary-bg); color: var(--c-primary-ink); border-radius: 10px; padding: 2px 12px; font-size: var(--fs-sm); }
.bar { display: inline-block; height: 10px; background: var(--c-primary); border-radius: 5px; vertical-align: middle; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: var(--sp-3); }
.ph { border: 1px dashed var(--c-border); border-radius: var(--radius); padding: var(--sp-3); display: flex; flex-direction: column; gap: var(--sp-2); }
</style>
