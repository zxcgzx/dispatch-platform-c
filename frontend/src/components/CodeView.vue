<script setup lang="ts">
// 代码标签页：只读高亮 + 行号 + 按标记折叠；点规格行跳到对应代码段，点代码段高亮对应规格行；custom_code 段标黄；可复制、下载。
// 代码页显示的代码就是试构建执行的代码（后端同一份 model.py）。
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'

hljs.registerLanguage('python', python)
const t = useTaskStore()
const collapsed = ref<Set<string>>(new Set())
const root = ref<HTMLElement | null>(null)

const lines = computed(() => t.code.split('\n'))
const highlighted = computed(() => {
  if (!t.code) return [] as string[]
  // 逐行高亮；多行字符串 / 注释跨行时个别行着色可能不准，不影响内容
  return lines.value.map((ln) => hljs.highlight(ln || ' ', { language: 'python' }).value)
})
// 标记 → 行区间（顶层标记按开始行排序）
const blocks = computed(() => t.markers.map((m) => ({ ...m, isDp: /^dp-/.test(m.id), isS: /^s-/.test(m.id), isB: /^B\d/.test(m.id) })))
const blockAt = computed(() => {
  const map = new Map<number, (typeof blocks.value)[number]>()
  blocks.value.forEach((b) => map.set(b.start, b))
  return map
})
const hiddenLine = computed(() => {
  const hide = new Set<number>()
  for (const b of blocks.value) if (collapsed.value.has(b.id)) for (let i = b.start + 1; i <= b.end; i++) hide.add(i)
  return hide
})
function blockOfLine(n: number) {
  return blocks.value.find((b) => b.start <= n && n <= b.end)
}
function toggle(id: string) {
  const s = new Set(collapsed.value)
  s.has(id) ? s.delete(id) : s.add(id)
  collapsed.value = s
}
function collapseAll(on: boolean) {
  collapsed.value = on ? new Set(blocks.value.map((b) => b.id)) : new Set()
}
function clickBlock(id: string) {
  t.setFocus(id, 'code')
  if (/^(dp|s)-/.test(id)) {
    /* 规格行在规格页高亮；切换标签后可见 */
  }
}
function gotoSpec(id: string) {
  t.setFocus(id, 'code')
  t.tab = 'spec'
}

// 规格行 → 代码：focus 变化且来源不是代码页时，展开并滚动到对应段
watch(() => t.focus, async (f) => {
  if (!f || t.tab !== 'code') return
  if (collapsed.value.has(f.id)) {
    const s = new Set(collapsed.value)
    s.delete(f.id)
    collapsed.value = s
  }
  await nextTick()
  root.value?.querySelector(`[data-block-start="${f.id}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
})
watch(() => t.tab, async (tab) => {
  if (tab === 'code' && t.focus) {
    await nextTick()
    root.value?.querySelector(`[data-block-start="${t.focus.id}"]`)?.scrollIntoView({ block: 'center' })
  }
})

async function copy() {
  try {
    await navigator.clipboard.writeText(t.code)
    ElMessage.success('已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = t.code
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    ElMessage.success('已复制')
  }
}
function download() {
  const blob = new Blob([t.code], { type: 'text/x-python;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `model_${t.taskId}_v${t.codeVersion}.py`
  a.click()
  URL.revokeObjectURL(a.href)
}
const focusId = computed(() => t.focus?.id)
</script>

<template>
  <div v-if="t.code" ref="root" class="cv" data-testid="code-view">
    <div class="bar row">
      <b>model.py</b><span class="sub">v{{ t.codeVersion }} · {{ lines.length }} 行 · 只读 · 这份代码就是“试构建”执行的代码</span>
      <span class="grow" />
      <el-button size="small" @click="collapseAll(true)">全部折叠</el-button>
      <el-button size="small" @click="collapseAll(false)">全部展开</el-button>
      <el-button size="small" data-testid="copy-code" @click="copy">复制</el-button>
      <el-button size="small" data-testid="download-code" @click="download">下载</el-button>
    </div>
    <div class="legend sub">
      <span class="sw dp" />Δπ 修改 <span class="sw s" />结构修改 <span class="sw cu" />custom 待审 <span class="sw inf" />待确认（未生效，只有注释）
      <span class="tip">点代码段标题 → 在规格页高亮对应行；在规格页点一行 → 回到这里会定位对应代码段</span>
    </div>
    <div class="code">
      <template v-for="(h, i) in highlighted" :key="i">
        <div v-if="!hiddenLine.has(i + 1)" class="ln" :class="{
          start: blockAt.has(i + 1), custom: blockOfLine(i + 1)?.custom, pend: blockOfLine(i + 1)?.pending,
          dp: blockOfLine(i + 1)?.isDp, s: blockOfLine(i + 1)?.isS, focus: blockOfLine(i + 1)?.id === focusId,
        }" :data-line="i + 1" :data-block-start="blockAt.get(i + 1)?.id" :data-block="blockOfLine(i + 1)?.id">
          <span class="no">{{ i + 1 }}</span>
          <span v-if="blockAt.get(i + 1)" class="fold" @click="toggle(blockAt.get(i + 1)!.id)">{{ collapsed.has(blockAt.get(i + 1)!.id) ? '▸' : '▾' }}</span>
          <span v-else class="fold" />
          <code v-html="h" @click="blockOfLine(i + 1) && clickBlock(blockOfLine(i + 1)!.id)" />
          <template v-if="blockAt.get(i + 1)">
            <button v-if="/^(dp|s)-/.test(blockAt.get(i + 1)!.id)" class="goto" :data-goto="blockAt.get(i + 1)!.id" @click="gotoSpec(blockAt.get(i + 1)!.id)">跳到规格行</button>
          </template>
        </div>
      </template>
    </div>
  </div>
  <div v-else class="sub empty">确认规格后才生成代码。 <StatusBadge feature="m3.code" small /></div>
</template>

<style scoped>
.cv { display: flex; flex-direction: column; gap: 6px; }
.bar { flex-wrap: wrap; }
.legend { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.sw { display: inline-block; width: 12px; height: 12px; border-radius: 2px; border: 1px solid var(--c-border); }
.sw.dp { background: var(--c-primary-bg); } .sw.s { background: var(--c-success-bg); } .sw.cu { background: var(--c-custom); } .sw.inf { background: var(--c-infer-bg); }
.tip { margin-left: 12px; color: var(--c-faint); }
.code { border: 1px solid var(--c-hairline); border-radius: var(--radius); background: #fbfbfa; max-height: calc(100vh - 360px); min-height: 320px; overflow: auto; font-family: var(--font-mono); font-size: 12.5px; line-height: 1.6; }
.ln { display: flex; align-items: flex-start; position: relative; white-space: pre; padding-right: 8px; }
.ln code { flex: 1; font-family: inherit; cursor: default; }
.no { width: 44px; text-align: right; color: var(--c-faint); padding-right: 10px; flex: none; user-select: none; }
.fold { width: 16px; flex: none; cursor: pointer; color: var(--c-muted); user-select: none; }
.ln.start { background: var(--c-surface-2); font-weight: 600; }
.ln.dp { background: var(--c-primary-bg); }
.ln.s { background: var(--c-success-bg); }
.ln.custom { background: var(--c-custom) !important; }
.ln.pend { background: var(--c-infer-bg) !important; }
.ln.focus { box-shadow: inset 3px 0 0 var(--c-primary), 0 0 0 1px var(--c-primary); background: var(--c-focus) !important; }
.goto { position: absolute; right: 8px; top: 1px; font: inherit; font-size: 11px; border: 1px solid var(--c-primary); color: var(--c-primary-ink); background: var(--c-surface); border-radius: 10px; padding: 0 8px; cursor: pointer; }
.empty { padding: var(--sp-5); border: 1px dashed var(--c-border); border-radius: var(--radius); }
</style>
