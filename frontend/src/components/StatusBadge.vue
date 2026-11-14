<script setup lang="ts">
// 状态徽标：已实现（绿）、黑盒（灰底）、接口预留（蓝色虚线框）、待开发（灰色虚线框）。
// 传 feature（功能登记 id）则状态从 features 取；也可直接传 status。推断项用琥珀色，不要和它混用。
import { computed } from 'vue'
import { featureTable, statusOf, type FeatureStatus } from '@/features'
import { useAppStore } from '@/stores/app'

const props = defineProps<{ feature?: string; status?: FeatureStatus; small?: boolean }>()
const app = useAppStore()
const st = computed<FeatureStatus>(() => {
  void app.featuresVersion // 登记表更新后重新取
  return props.status ?? (props.feature ? statusOf(props.feature) : 'todo')
})
const label = computed(() => featureTable().status_labels[st.value])
</script>

<template>
  <span class="badge" :class="[`st-${st}`, { small }]" :title="label">{{ label }}</span>
</template>

<style scoped>
.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: var(--fs-xs);
  line-height: 18px;
  white-space: nowrap;
  border: 1px solid transparent;
}
.badge.small { padding: 0 6px; line-height: 16px; font-size: 11px; }
.st-implemented { color: var(--c-st-impl); background: var(--c-st-impl-bg); border-color: var(--c-st-impl); }
.st-blackbox { color: #fff; background: var(--c-st-black); border-color: var(--c-st-black); }
.st-reserved { color: var(--c-st-reserved); background: var(--c-st-reserved-bg); border: 1px dashed var(--c-st-reserved); }
.st-todo { color: var(--c-st-todo); background: var(--c-st-todo-bg); border: 1px dashed var(--c-st-todo); }
</style>
