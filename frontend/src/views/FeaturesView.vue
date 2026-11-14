<script setup lang="ts">
// 功能清单：按 M1–M9 列出课题 4 的全部功能和状态，供老师审查。数据来自功能登记表（features.ts / /api/features）。
import { computed } from 'vue'
import { featureTable, type Feature, type FeatureStatus } from '@/features'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'

const app = useAppStore()
const groups = computed(() => {
  void app.featuresVersion
  const t = featureTable()
  return Object.keys(t.modules).map((m) => ({ id: m, name: t.modules[m], items: t.features.filter((f) => f.module === m) }))
})
const summary = computed(() => {
  void app.featuresVersion
  const t = featureTable()
  const c: Record<string, number> = {}
  t.features.forEach((f: Feature) => (c[f.status] = (c[f.status] || 0) + 1))
  return (['implemented', 'blackbox', 'reserved', 'todo'] as FeatureStatus[]).map((s) => ({ s, n: c[s] || 0 }))
})
</script>

<template>
  <div class="page">
    <h2>功能清单</h2>
    <p class="sub">按 M1–M9 列出课题 4 的全部功能。状态唯一来源是功能登记表（后端 <code>/api/features</code> 与前端 <code>features.ts</code> 同源），界面上所有按钮、标签页、卡片的状态徽标都从这里取。</p>
    <div class="row sums" data-testid="feature-summary">
      <div v-for="x in summary" :key="x.s" class="sum card"><StatusBadge :status="x.s" /><b>{{ x.n }}</b> 项</div>
    </div>
    <div v-for="g in groups" :key="g.id" class="card card-pad grp" :data-module="g.id">
      <div class="card-title">{{ g.id }} · {{ g.name }}</div>
      <table class="table-plain">
        <thead><tr><th style="width: 220px">功能</th><th style="width: 100px">状态</th><th>说明</th></tr></thead>
        <tbody>
          <tr v-for="f in g.items" :key="f.id" :data-feature="f.id">
            <td>{{ f.name }}</td>
            <td><StatusBadge :status="f.status" /></td>
            <td class="sub">{{ f.note }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.sums { margin: var(--sp-3) 0; gap: var(--sp-3); }
.sum { padding: 8px 16px; display: flex; gap: var(--sp-2); align-items: center; }
.grp { margin-bottom: var(--sp-3); }
</style>
