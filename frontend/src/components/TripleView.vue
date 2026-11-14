<script setup lang="ts">
// 规格 / 公式 / 代码三栏对照：并排显示同一版本的三种表达，点任一处，另两处同步高亮到同一条目。
import { computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import Tex from '@/components/Tex.vue'

const t = useTaskStore()
const spec = computed(() => t.spec)
const f = computed(() => t.formulas)
const items = computed(() => {
  const s = spec.value
  if (!s) return []
  const fm = new Map((f.value?.changes ?? []).map((c) => [c.id, c]))
  const mk = new Map(t.markers.map((m) => [m.id, m]))
  const lines = t.code.split('\n')
  const snippet = (id: string) => {
    const m = mk.get(id)
    return m ? lines.slice(m.start - 1, Math.min(m.end, m.start + 7)).join('\n') : ''
  }
  const rows: { id: string; spec: string; latex: string; code: string; affects: string[] }[] = []
  s.delta_pi.forEach((d) => rows.push({
    id: d.id, spec: `${d.target}.${d.param} ${d.source === 'inferred' ? (d.value == null ? '（推断，幅度待确认）' : `（推断）× ${d.value}`) : `${d.operation} ${d.value}`}`,
    latex: fm.get(d.id)?.latex ?? '', code: snippet(d.id), affects: fm.get(d.id)?.affects ?? [],
  }))
  s.structural.forEach((o) => rows.push({
    id: o.id, spec: `${t.meta?.operators?.[o.op_id]?.name ?? o.op_id}${Object.keys(o.params ?? {}).length ? ' ' + JSON.stringify(o.params) : ''}`,
    latex: fm.get(o.id)?.latex ?? '', code: snippet(o.id), affects: fm.get(o.id)?.affects ?? [],
  }))
  return rows
})
const on = (id: string) => t.focus?.id === id
</script>

<template>
  <div class="tv" data-testid="triple-view">
    <p class="sub">同一条修改的三种表达并排放置：左边是规格，中间是公式，右边是生成的代码。点一行，另外两处同步高亮。</p>
    <div v-if="!items.length" class="sub">本版没有参数或结构修改，三栏都是基础模型。</div>
    <div v-for="r in items" :key="r.id" class="row3" :class="{ on: on(r.id) }" :data-triple="r.id" @click="t.setFocus(r.id, 'triple')">
      <div class="c1"><b class="tag">{{ r.id }}</b><span>{{ r.spec }}</span><div v-if="r.affects.length" class="sub">影响 {{ r.affects.join('、') }}</div></div>
      <div class="c2"><Tex v-if="r.latex" :tex="r.latex" /></div>
      <pre class="c3">{{ r.code || '（确认版本后生成代码）' }}</pre>
    </div>
  </div>
</template>

<style scoped>
.tv { display: flex; flex-direction: column; gap: 8px; }
.row3 { display: grid; grid-template-columns: 1fr 1.2fr 1.6fr; gap: 12px; border: 1px solid var(--c-hairline); border-radius: var(--radius); padding: 10px 12px; background: var(--c-surface); cursor: pointer; }
.row3.on { border-color: var(--c-primary); background: var(--c-primary-bg); }
.c1 { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-sm); }
.tag { align-self: flex-start; background: var(--c-primary); color: #fff; border-radius: 10px; padding: 0 10px; font-size: var(--fs-xs); }
.c3 { margin: 0; background: #111; color: #d6e2d6; border-radius: var(--radius-sm); padding: 8px 10px; font-size: 11.5px; line-height: 1.55; overflow: auto; max-height: 190px; white-space: pre; }
</style>
