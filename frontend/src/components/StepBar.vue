<script setup lang="ts">
// 七步流程条：指令输入 → 层级判定 → 规格确认 → 去幻觉校验 → 求解 → 结果与地图 → 风险评估。
// 每步状态：未开始 / 进行中 / 已完成 / 有错误；已完成（或有错误）的步骤可点击回看。
export type StepState = 'idle' | 'active' | 'done' | 'error'
defineProps<{ states: StepState[]; current: number }>()
const emit = defineEmits<{ (e: 'go', step: number): void }>()
const names = ['指令输入', '层级判定', '规格确认', '去幻觉校验', '求解', '结果与地图', '风险评估']
</script>

<template>
  <div class="steps" data-testid="stepbar">
    <button
      v-for="(n, i) in names" :key="n" class="step" :class="[states[i], { cur: current === i + 1 }]"
      :data-step="i + 1" :data-state="states[i]" :disabled="states[i] === 'idle'" @click="emit('go', i + 1)"
    >
      <span class="no">{{ i + 1 }}</span>{{ n }}
      <span v-if="states[i] === 'done'" class="mark ok">✓</span>
      <span v-else-if="states[i] === 'error'" class="mark bad">!</span>
      <span v-else-if="states[i] === 'active'" class="mark run">…</span>
    </button>
  </div>
</template>

<style scoped>
.steps { display: flex; gap: var(--sp-2); }
.step {
  flex: 1; height: 36px; border-radius: var(--radius); background: transparent; font: inherit; font-size: var(--fs-sm);
  border: 1.25px solid var(--c-border); color: var(--c-muted); cursor: pointer; white-space: nowrap;
  display: flex; align-items: center; justify-content: center; gap: 6px;
}
.step:disabled { cursor: default; }
.step .no { font-weight: 600; }
.step.done { border-color: var(--c-success); color: var(--c-ink); }
.step.error { border-color: var(--c-danger); color: var(--c-danger); background: var(--c-danger-bg); }
.step.active, .step.cur { background: var(--c-primary-bg); border: 2px solid var(--c-primary); color: var(--c-ink); font-weight: 600; }
.mark.ok { color: var(--c-success); }
.mark.bad { color: var(--c-danger); font-weight: 700; }
.mark.run { color: var(--c-primary); }
</style>
