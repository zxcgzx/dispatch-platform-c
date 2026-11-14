<script setup lang="ts">
// 公式标签页：顶部“本版改动”（dp-1、s-1 标签）；下面是基础模型 B1–B9，受影响的块高亮；新增约束显示为新块。
import { computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import Tex from '@/components/Tex.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const t = useTaskStore()
const f = computed(() => t.formulas)
const hlCount = computed(() => f.value?.blocks.filter((b) => b.highlight).length ?? 0)
function jumpCode(id: string) {
  t.setFocus(id, 'formula')
  if (t.hasVersion) t.tab = 'code'
}
function jumpSpec(id: string) {
  t.setFocus(id, 'formula')
  t.tab = 'spec'
}
</script>

<template>
  <div v-if="f" class="fv" data-testid="formula-view">
    <section class="card card-pad">
      <div class="card-title">本版改动 <span class="sub">每条 Δπ 和 s 带标签；点标签跳到规格行</span></div>
      <div v-if="!f.changes.length" class="sub">本版没有参数或结构修改，公式即基础模型。</div>
      <div v-for="c in f.changes" :key="c.id" class="chg" :class="{ infer: c.inferred, custom: c.custom, pend: c.pending }" :data-change="c.id">
        <button class="tag" :class="{ infer: c.inferred }" @click="jumpSpec(c.id)">{{ c.id }}</button>
        <span class="title">{{ c.title }}</span>
        <Tex :tex="c.latex" />
        <span v-if="c.inferred" class="infer-tag">推断项{{ c.pending ? ' · 待确认' : c.confirmed ? ' · 已确认' : ' · 未确认' }}</span>
        <el-tag v-if="c.custom" size="small" type="warning">custom 待审</el-tag>
        <span v-if="c.affects.length" class="sub">影响 {{ c.affects.join('、') }}</span>
        <el-button v-if="t.hasVersion" size="small" text type="primary" @click="jumpCode(c.id)">看代码</el-button>
      </div>
    </section>

    <section class="card card-pad">
      <div class="card-title">目标
        
      </div>
      <div class="obj"><Tex :tex="f.objective.latex" display /></div>
      <div v-if="f.objective.note" class="sub">{{ f.objective.note }}</div>
      <div v-for="x in f.objective.terms" :key="x.id" class="sub">+ 目标项 <button class="tag" @click="jumpSpec(x.id)">{{ x.id }}</button></div>
    </section>

    <section class="card card-pad">
      <div class="card-title">基础模型：多时段 AC-OTS <span class="sub">受影响的块高亮（本版 {{ hlCount }} 块）<template v-if="f.fixed_topology">；固定拓扑：去掉 0-1 变量</template></span></div>
      <div v-for="b in f.blocks" :key="b.id" class="blk" :class="{ hl: b.highlight, abs: b.abstract }" :data-block="b.id" :data-highlight="b.highlight">
        <div class="bh">
          <b>{{ b.id }}</b> {{ b.title }}
          <el-tag v-if="b.abstract" size="small" effect="plain">抽象块</el-tag>
          <button v-for="c in b.changed_by" :key="c" class="tag" @click="jumpSpec(c)">{{ c }}</button>
          <el-button v-if="t.hasVersion" size="small" text type="primary" @click="jumpCode(b.id)">看代码</el-button>
        </div>
        <Tex :tex="b.latex" display />
        <div v-if="b.note" class="sub">{{ b.note }}</div>
      </div>
    </section>

    <section v-if="f.new_blocks.length" class="card card-pad newb">
      <div class="card-title">新增约束 / 结构块</div>
      <div v-for="b in f.new_blocks" :key="b.id" class="blk hl" :data-newblock="b.id" :class="{ custom: b.custom }">
        <div class="bh"><b>{{ b.id }}</b> {{ b.title }} <el-tag size="small" type="success">新块</el-tag>
          <el-tag v-if="b.custom" size="small" type="warning">custom 待审</el-tag>
          <button class="tag" @click="jumpSpec(b.id)">{{ b.id }}</button></div>
        <Tex :tex="b.latex" display />
      </div>
    </section>
  </div>
  <div v-else class="sub empty">解析指令后，这里显示公式。<StatusBadge feature="m3.formula" small /></div>
</template>

<style scoped>
.fv { display: flex; flex-direction: column; gap: var(--sp-3); }
.chg { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 6px 8px; border-radius: var(--radius-sm); border: 1px solid var(--c-hairline); margin-bottom: 6px; }
.chg.infer { background: var(--c-infer-bg); border-color: var(--c-infer-line); }
.chg.custom { background: var(--c-custom); }
.title { font-weight: 600; }
.tag { font: inherit; font-size: var(--fs-xs); font-family: var(--font-mono); border: 1px solid var(--c-primary); color: var(--c-primary-ink); background: var(--c-primary-bg); border-radius: 10px; padding: 0 8px; cursor: pointer; }
.tag.infer { border-color: var(--c-infer-line); color: var(--c-infer); background: var(--c-surface); }
.blk { border: 1px solid var(--c-hairline); border-radius: var(--radius); padding: 8px 12px; margin-bottom: 8px; }
.blk.hl { border: 2px solid var(--c-primary); background: var(--c-primary-bg); }
.blk.abs { border-style: dashed; }
.blk.custom { background: var(--c-custom); }
.bh { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 2px; }
.obj { overflow-x: auto; }
.empty { padding: var(--sp-5); border: 1px dashed var(--c-border); border-radius: var(--radius); }
</style>
