<script setup lang="ts">
// 跨课题接口：课题 2（测点数据、大模型、方案回写）与课题 3（风险评估、协商、reward）各一块，画出数据流向与当前状态。
import { computed, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import StatusBadge from '@/components/StatusBadge.vue'

const app = useAppStore()
onMounted(() => app.init())
const st = (id: string) => app.integrations.find((i) => i.id === id)
const lamp = (id: string) => st(id)?.state ?? 'none'
const label = (id: string) => st(id)?.state_label ?? '未接入'

const flows = computed(() => [
  { from: '课题 2', to: '本平台', name: '测点数据（静态 / 动态表）', feature: 'm1.tp_data', state: 't2_data', route: '/measure', go: '测点转换' },
  { from: '课题 2', to: '本平台', name: '大模型：指令 → 规格 JSON', feature: 'm1.llm_t2', state: 't2_llm', route: '/data', go: '接口说明' },
  { from: '本平台', to: '课题 2', name: '方案回写：开断方案 → 开关动作', feature: 'm6.writeback', state: 't2_data', route: '/measure', go: '回写清单' },
  { from: '本平台', to: '课题 3', name: '方案与指标 → 风险评估', feature: 'm7.risk', state: 'risk', route: '/workbench', go: '风险评估' },
  { from: '课题 3', to: '本平台', name: '风险等级与原因 → 协商调整', feature: 'm7.negotiate', state: 'risk', route: '/workbench', go: '协商' },
  { from: '课题 3', to: '本平台', name: 'reward：风险折算奖励', feature: 'm7.reward', state: 'risk', route: '/workbench', go: 'Reward' },
])
</script>

<template>
  <div class="page">
    <h2>跨课题接口</h2>
    <p class="sub">本平台与课题 2（数据与大模型）、课题 3（风险评估）之间的六条数据流。每条流标明方向、当前状态，并可直接跳到对应功能页。</p>

    <div class="diagram" data-testid="flow-diagram">
      <div class="col">
        <div class="box t2"><b>课题 2</b><span>测点数据 · 大模型</span><div class="lamp"><i class="dot" :class="lamp('t2_data')" />数据 {{ label('t2_data') }}</div><div class="lamp"><i class="dot" :class="lamp('t2_llm')" />大模型 {{ label('t2_llm') }}</div></div>
      </div>
      <svg class="arrows" viewBox="0 0 220 220" aria-hidden="true">
        <defs><marker id="ah" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#1f5fc4" /></marker></defs>
        <line x1="8" y1="50" x2="210" y2="50" stroke="#1f5fc4" stroke-width="2" marker-end="url(#ah)" />
        <line x1="8" y1="78" x2="210" y2="78" stroke="#1f5fc4" stroke-width="2" marker-end="url(#ah)" />
        <line x1="212" y1="142" x2="10" y2="142" stroke="#8c1515" stroke-width="2" marker-end="url(#ah2)" />
        <defs><marker id="ah2" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8c1515" /></marker></defs>
        <text x="110" y="42" text-anchor="middle" font-size="11" fill="#555">测点数据</text>
        <text x="110" y="96" text-anchor="middle" font-size="11" fill="#555">大模型规格</text>
        <text x="110" y="160" text-anchor="middle" font-size="11" fill="#555">开关动作回写</text>
      </svg>
      <div class="col center">
        <div class="box me"><b>运行方式智能调整平台C</b><span>建模 · 校验 · 求解 · 结果</span><div class="lamp"><i class="dot" :class="lamp('solver')" />求解器 {{ label('solver') }}</div></div>
      </div>
      <svg class="arrows" viewBox="0 0 220 220" aria-hidden="true">
        <line x1="8" y1="50" x2="210" y2="50" stroke="#1f5fc4" stroke-width="2" marker-end="url(#ah)" />
        <line x1="212" y1="96" x2="10" y2="96" stroke="#8c1515" stroke-width="2" marker-end="url(#ah2)" />
        <line x1="212" y1="142" x2="10" y2="142" stroke="#8c1515" stroke-width="2" marker-end="url(#ah2)" />
        <text x="110" y="42" text-anchor="middle" font-size="11" fill="#555">方案与指标</text>
        <text x="110" y="88" text-anchor="middle" font-size="11" fill="#555">风险等级与原因</text>
        <text x="110" y="134" text-anchor="middle" font-size="11" fill="#555">reward</text>
      </svg>
      <div class="col">
        <div class="box t3"><b>课题 3</b><span>风险评估</span><div class="lamp"><i class="dot" :class="lamp('risk')" />{{ label('risk') }}</div></div>
      </div>
    </div>

    <section class="card card-pad">
      <div class="card-title">数据流清单</div>
      <table class="table-plain" data-testid="flow-table">
        <thead><tr><th>方向</th><th>内容</th><th>状态</th><th>接口</th><th /></tr></thead>
        <tbody>
          <tr v-for="f in flows" :key="f.name">
            <td>{{ f.from }} → {{ f.to }}</td><td>{{ f.name }}</td>
            <td><StatusBadge :feature="f.feature" small /> <span class="sub">{{ label(f.state) }}</span></td>
            <td class="sub">{{ st(f.state)?.request?.split('\n')[0] }}</td>
            <td><router-link :to="f.route">{{ f.go }}</router-link></td>
          </tr>
        </tbody>
      </table>
    </section>

    <div class="two">
      <section class="card card-pad">
        <div class="card-title">课题 2 接口</div>
        <div v-for="id in ['t2_data', 't2_llm']" :key="id" class="it"><b>{{ st(id)?.name }}</b>　<span class="sub">{{ st(id)?.state_label }}</span>
          <div class="sub">{{ st(id)?.detail }}</div><div class="mono sub pre">{{ st(id)?.request }}</div><div class="mono sub pre">→ {{ st(id)?.response }}</div></div>
      </section>
      <section class="card card-pad">
        <div class="card-title">课题 3 接口</div>
        <div class="it"><b>{{ st('risk')?.name }}</b>　<span class="sub">{{ st('risk')?.state_label }}</span>
          <div class="sub">{{ st('risk')?.detail }}</div><div class="mono sub pre">{{ st('risk')?.request }}</div><div class="mono sub pre">→ {{ st('risk')?.response }}</div></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.diagram { display: grid; grid-template-columns: 1fr 150px 1.2fr 150px 1fr; align-items: center; background: var(--c-surface); border: 1px solid var(--c-hairline); border-radius: 12px; padding: 18px; margin: var(--sp-3) 0; box-shadow: var(--shadow); }
.arrows { width: 100%; height: 150px; }
.box { border: 1.5px solid var(--c-border); border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; min-height: 130px; justify-content: center; }
.box b { font-size: 16px; } .box span { color: var(--c-muted); font-size: 12.5px; }
.box.me { border-color: var(--c-primary); background: var(--c-primary-bg); text-align: center; }
.box.t2 { border-color: #2a9d4a; } .box.t3 { border-color: #c98a00; }
.lamp { font-size: 12px; display: flex; align-items: center; gap: 6px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); margin-top: var(--sp-3); }
.it { margin-bottom: 12px; } .pre { white-space: pre-wrap; }
section { margin-top: var(--sp-3); }
</style>
