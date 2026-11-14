<script setup lang="ts">
// M9 问题分解与多智能体：占位页，只写计划功能，全部标“待开发”，不放任何伪造数据。
import StatusBadge from '@/components/StatusBadge.vue'

const sections = [
  {
    title: '任务 2：问题分解',
    items: [
      { feature: 'm9.decompose', name: '问题类型识别', desc: '判断调度任务属于哪类运行方式调整问题（如 OTS、OPF、检修安排）。' },
      { feature: 'm9.decompose', name: '分解策略选择', desc: '按网络规模与耦合关系选择分区或分时段分解策略。' },
      { feature: 'm9.decompose', name: '子问题网络', desc: '展示子问题之间的耦合关系图。' },
      { feature: 'm9.knowledge', name: '知识库', desc: '建模规则与调度规程知识库（参照 IBM Bob 的规则库）。' },
    ],
  },
  {
    title: '任务 4：多智能体协同',
    items: [
      { feature: 'm9.multiagent', name: '子问题智能体', desc: '每个子问题一个智能体，显示状态与当前任务。' },
      { feature: 'm9.multiagent', name: '边端协同', desc: '边缘侧与中心侧的协同过程。' },
      { feature: 'm9.multiagent', name: '全局收敛', desc: '各子问题的边界信息交换与全局收敛情况。' },
    ],
  },
]
</script>

<template>
  <div class="page">
    <h2>问题分解与多智能体 <StatusBadge feature="m9.decompose" /></h2>
    <p class="sub">本页为 M9 占位：中期前只放页面和功能说明，是否在中期演示由老师定。以下功能全部待开发，页面内没有任何示例数据。</p>
    <div v-for="s in sections" :key="s.title" class="card card-pad grp">
      <div class="card-title">{{ s.title }}</div>
      <div class="cards">
        <div v-for="it in s.items" :key="it.name" class="ph" data-testid="m9-card">
          <div class="row"><b>{{ it.name }}</b><StatusBadge :feature="it.feature" small /></div>
          <div class="sub">{{ it.desc }}</div>
          <div class="empty">待开发</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grp { margin-top: var(--sp-3); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--sp-3); }
.ph { border: 1px dashed var(--c-border); border-radius: var(--radius); padding: var(--sp-3); display: flex; flex-direction: column; gap: var(--sp-2); }
.empty { margin-top: var(--sp-2); height: 70px; display: grid; place-items: center; color: var(--c-faint); background: var(--c-st-todo-bg); border-radius: var(--radius-sm); }
</style>
