<script setup lang="ts">
// 地图页：真实行政区划底图 + 网架。可单独看，也可选一个已求解的任务叠加方案。
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import DaliMap from '@/components/DaliMap.vue'
import type { SolveResult } from '@/types/later'

const tasks = ref<any[]>([])
const tid = ref('')
const result = ref<SolveResult | null>(null)
const outage = ref<string[]>([])

onMounted(async () => {
  tasks.value = (await api.get<any>('/tasks')).tasks.filter((t: any) => t.version)
})
async function pick() {
  result.value = null
  outage.value = []
  if (!tid.value) return
  const r = await api.get<any>(`/tasks/${tid.value}/results`)
  result.value = r.result
  const v = await api.get<any>(`/tasks/${tid.value}/versions/${r.version}`)
  outage.value = (v.spec.delta_pi ?? []).filter((d: any) => d.param === 'BR_STATUS' && d.value === 0).map((d: any) => d.target)
}
</script>

<template>
  <div class="page">
    <div class="head">
      <div><h2>电网地图</h2><p class="sub">大理白族自治州行政区划底图，叠加 905 节点网架；选择一个已求解的任务，可在地图上看到方案里被开断的线路。</p></div>
      <el-select v-model="tid" clearable placeholder="叠加某个任务的方案" style="width: 320px" data-testid="map-task" @change="pick">
        <el-option v-for="t in tasks" :key="t.id" :value="t.id" :label="`${t.id} · ${t.instruction.slice(0, 26)}`" />
      </el-select>
    </div>
    <div class="card card-pad"><DaliMap :result="result" :outage-rows="outage" :height="640" /></div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-bottom: 10px; }
.head h2 { margin-bottom: 2px; }
</style>
