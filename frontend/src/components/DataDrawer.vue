<script setup lang="ts">
// “数据概况”抽屉：数据事实与质量的摘要（完整版在“数据与接口”页）。
import { onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useAppStore } from '@/stores/app'

const open = defineModel<boolean>({ default: false })
const app = useAppStore()
const sum = ref<any>(null)
watch(open, async (v) => {
  if (v && !sum.value && app.defaultSnapshot) sum.value = await api.get(`/snapshots/${app.defaultSnapshot}/summary`)
})
onMounted(() => { void 0 })
const lv: Record<string, string> = { warn: '警告', info: '提示', error: '错误' }
</script>

<template>
  <el-drawer v-model="open" title="数据概况" size="460px" append-to-body>
    <div v-if="sum" data-testid="data-drawer">
      <p class="sub">{{ sum.file }} · 断面时刻 {{ sum.facts.time }}（来源：{{ sum.time_source === 'dict' ? 'Dict Info' : '文件名' }}）</p>
      <table class="table-plain">
        <tbody>
          <tr><th>规模</th><td>母线 {{ sum.facts.counts.bus }} · 机组 {{ sum.facts.counts.gen }} · 支路 {{ sum.facts.counts.branch }}</td></tr>
          <tr><th>BUS_TYPE</th><td>PQ {{ sum.facts.bus_types['PQ'] }} · PV {{ sum.facts.bus_types['PV'] }} · 平衡 {{ sum.facts.bus_types['平衡节点'] }}</td></tr>
          <tr><th>孤岛型支路</th><td>{{ sum.facts.isolating_branches }} 条（一断开就形成孤岛）</td></tr>
          <tr><th>网状部分</th><td>{{ sum.facts.meshed_branches }} 条</td></tr>
          <tr><th>PD / PG</th><td>{{ sum.facts.totals.pd_mw }} / {{ sum.facts.totals.pg_mw }} MW</td></tr>
        </tbody>
      </table>
      <h4 style="margin: 14px 0 6px">数据质量</h4>
      <div v-for="q in sum.quality.filter((x: any) => x.count > 0)" :key="q.code" class="q">
        <span :class="'lv-' + (q.level === 'warn' ? 'warn' : 'info')">[{{ lv[q.level] }}]</span> {{ q.title }}：<b>{{ q.count }}</b>
      </div>
      <router-link to="/data" style="display: inline-block; margin-top: 12px">查看完整数据与接口页 →</router-link>
    </div>
    <div v-else class="sub">加载中…</div>
  </el-drawer>
</template>

<style scoped>
.q { font-size: var(--fs-sm); line-height: 1.8; }
</style>
