<script setup lang="ts">
// KaTeX 渲染（字体随包打包，离线可用）。渲染失败时退回显示源码，不让整页崩。
import { computed } from 'vue'
import katex from 'katex'

const props = defineProps<{ tex: string; display?: boolean }>()
const html = computed(() => {
  try {
    return katex.renderToString(props.tex, { displayMode: !!props.display, throwOnError: false, strict: 'ignore', output: 'html' })
  } catch {
    return `<code>${props.tex.replace(/</g, '&lt;')}</code>`
  }
})
</script>

<template><span class="tex" v-html="html" /></template>

<style scoped>
.tex { max-width: 100%; overflow-x: auto; overflow-y: hidden; display: inline-block; vertical-align: middle; }
</style>
