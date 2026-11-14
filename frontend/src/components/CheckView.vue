<script setup lang="ts">
// 校验标签页：五层列表，每层亮红 / 黄 / 绿灯；点一条结果，跳到规格页对应行并高亮；“外部方法”一行显示方法组接口状态。
import { computed, ref } from 'vue'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'
import type { Finding } from '@/types/api'

const t = useTaskStore()
const rep = computed(() => t.report)
const open = ref<Record<number, boolean>>({ 1: true, 2: true, 3: true, 4: true, 5: true })
const lvText = { error: '错误', warn: '警告', info: '提示' } as const
const lamp = { red: '红', yellow: '黄', green: '绿' } as const

function locate(f: Finding) {
  if (f.item_id && f.item_id !== 'omega') {
    t.setFocus(f.item_id, 'check')
    t.tab = 'spec'
  } else if (f.layer === 4 && f.code === 'I403') {
    t.tab = 'spec'
  }
}
const i503 = computed(() => rep.value?.layers[4]?.findings.find((f) => f.code === 'I503'))
const i403 = computed(() => rep.value?.layers[3]?.findings.find((f) => f.code === 'I403'))
</script>

<template>
  <div v-if="rep" class="ck" data-testid="check-view">
    <div class="sum row">
      <b>v{{ t.reportVersion }} 校验结果</b>
      <span class="lv-error">错误 {{ rep.counts.error }}</span><span class="lv-warn">警告 {{ rep.counts.warn }}</span><span class="lv-info">提示 {{ rep.counts.info }}</span>
      <span class="sub">错误会阻止进入求解，警告需你确认。</span>
      <span class="grow" />
      <el-button size="small" :loading="t.busy" data-testid="recheck" @click="t.recheck()">重新校验</el-button>
    </div>

    <section v-for="L in rep.layers" :key="L.layer" class="layer card" :data-layer="L.layer" :data-status="L.status">
      <div class="lh" @click="open[L.layer] = !open[L.layer]">
        <i class="lamp" :class="L.status" :title="lamp[L.status]" />
        <b>第 {{ L.layer }} 层 · {{ L.name }}</b>
        <span class="sub">{{ L.findings.length ? `${L.findings.length} 条` : '通过' }}</span>
        <span class="grow" />
        <span class="sub">{{ open[L.layer] ? '收起' : '展开' }}</span>
      </div>
      <div v-show="open[L.layer]" class="lb">
        <div v-if="!L.findings.length" class="sub ok">无问题</div>
        <div
          v-for="(f, i) in L.findings" :key="i" class="fd" :class="[f.level, { loc: !!f.item_id }]" :data-code="f.code" :data-item="f.item_id" @click="locate(f)"
        >
          <span class="code mono">{{ f.code }}</span>
          <span class="lvl" :class="'lv-' + f.level">{{ lvText[f.level] }}</span>
          <div class="grow">
            <div>{{ f.message }}</div>
            <div v-if="f.suggestion" class="sub">建议：{{ f.suggestion }}</div>
            <div v-if="f.source !== '内置'" class="sub">来源：{{ f.source }}</div>
          </div>
          <el-button v-if="f.item_id && f.item_id !== 'omega'" size="small" text type="primary" :data-locate="f.item_id">定位到 {{ f.item_id }}</el-button>
        </div>

        <template v-if="L.layer === 5">
          <div class="ext row" data-testid="external-row">
            <i class="lamp" :class="rep.external.state === 'connected' ? 'green' : rep.external.state === 'error' ? 'red' : 'off'" />
            <b>{{ rep.external.label }}</b><StatusBadge feature="m4.ext_check" small />
            <span class="sub">去幻觉方法：POST {METHOD_ENDPOINT}/check，响应 findings 合并进本层并注明来源</span>
          </div>
          <div v-if="i503?.data" class="bt" data-testid="backtranslation">
            <div class="btc"><div class="sub">指令原文</div><div class="bx">{{ i503.data.instruction }}</div></div>
            <div class="btc"><div class="sub">规格回译（逐条）</div>
              <div v-for="it in i503.data.items" :key="it.id" class="bi" @click="it.id !== 'omega' && locate({ item_id: it.id, layer: 5 } as any)"><b class="mono">{{ it.id === 'omega' ? 'ω' : it.id }}</b> {{ it.text }}</div>
            </div>
          </div>
        </template>
        <template v-if="L.layer === 4 && i403?.data?.trial">
          <div class="sub trial" data-testid="trial-info">
            试构建：
            <template v-if="i403.data.trial.status === 'ok'">T = 1、不含 N−1 → 变量 {{ i403.data.trial.vars.toLocaleString() }} · 0-1 变量 {{ i403.data.trial.binary.toLocaleString() }} · 约束 {{ i403.data.trial.constraints.toLocaleString() }}（{{ i403.data.trial.build_s }} s）</template>
            <template v-else>{{ i403.data.trial.reason ?? i403.data.trial.error ?? i403.data.trial.status }}</template>
          </div>
        </template>
      </div>
    </section>
  </div>
  <div v-else class="sub empty">确认规格后才做校验。<StatusBadge feature="m4.checks" small /></div>
</template>

<style scoped>
.ck { display: flex; flex-direction: column; gap: var(--sp-2); }
.sum { gap: 14px; flex-wrap: wrap; }
.layer { overflow: hidden; }
.lh { display: flex; align-items: center; gap: 10px; padding: 10px 14px; cursor: pointer; background: var(--c-surface-2); }
.lamp { width: 14px; height: 14px; border-radius: 50%; display: inline-block; flex: none; border: 1px solid rgba(0, 0, 0, 0.12); }
.lamp.red { background: var(--c-danger); } .lamp.yellow { background: #e8b630; } .lamp.green { background: var(--c-success); } .lamp.off { background: transparent; border: 2px dashed var(--c-faint); }
.lb { padding: 8px 14px; }
.ok { padding: 6px 0; }
.fd { display: flex; gap: 10px; align-items: flex-start; padding: 8px 6px; border-bottom: 1px solid var(--c-hairline); font-size: var(--fs-sm); line-height: 1.55; }
.fd.loc { cursor: pointer; }
.fd.loc:hover { background: var(--c-primary-bg); }
.fd.error { background: var(--c-danger-bg); }
.fd.warn { background: var(--c-warn-bg); }
.code { font-weight: 600; min-width: 44px; }
.lvl { min-width: 32px; font-weight: 600; }
.ext { padding: 8px 6px; gap: 8px; flex-wrap: wrap; border-top: 1px dashed var(--c-border); margin-top: 6px; }
.bt { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 8px; }
.bx, .bi { background: var(--c-surface-2); padding: 8px 10px; border-radius: var(--radius-sm); margin-top: 4px; line-height: 1.7; font-size: var(--fs-sm); }
.bi { cursor: pointer; margin-bottom: 4px; } .bi:hover { background: var(--c-primary-bg); }
.trial { margin-top: 6px; }
.empty { padding: var(--sp-5); border: 1px dashed var(--c-border); border-radius: var(--radius); }
</style>
