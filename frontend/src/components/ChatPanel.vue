<script setup lang="ts">
// 对话与追问：首页是一条宽输入框（场景卡片在上方）；有任务后变成左栏对话流，系统追问带选项按钮。
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useTaskStore } from '@/stores/task'
import StatusBadge from '@/components/StatusBadge.vue'
import InstructionBuilder from '@/components/InstructionBuilder.vue'
import type { Question } from '@/types/api'

const props = defineProps<{ compact?: boolean }>()
const t = useTaskStore()
const input = ref('')
const scroller = ref<HTMLElement | null>(null)
const manual = ref<Record<string, string>>({})
const picked = ref<Record<string, string[]>>({})
const showManual = ref<Record<string, boolean>>({})

onMounted(() => t.loadMeta())
watch(() => t.messages.length, async () => {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
})

const questions = computed(() => t.parse?.questions ?? [])
const hasTask = computed(() => !!t.state)
const placeholder = computed(() => (hasTask.value ? '补充条件，会并入原指令重新解析…' : '也可以直接输入调度指令，例如：母线 43 的有功负荷提高 20%'))

async function fromBuilder(text: string, go: boolean) {
  input.value = text
  if (go) await send()
}
async function send() {
  const text = input.value.trim()
  if (!text || t.busy) return
  input.value = ''
  await t.start(text)
}
async function choose(q: Question, value: string) {
  if (t.busy) return
  if (value === '__manual__') {
    showManual.value[q.id] = true
    return
  }
  await t.answer(q.id, value)
}
function toggle(q: Question, v: string) {
  const cur = picked.value[q.id] ?? []
  picked.value[q.id] = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]
}
async function submitPicked(q: Question) {
  const vals = picked.value[q.id] ?? []
  if (!vals.length) return
  if (vals.includes('__all__')) return t.answer(q.id, '__all__')
  await t.answer(q.id, vals.sort((a, b) => +a - +b).join(','))
}
async function submitManual(q: Question) {
  const v = (manual.value[q.id] ?? '').trim()
  if (!v) return
  await t.answer(q.id, v)
  manual.value[q.id] = ''
  showManual.value[q.id] = false
}
</script>

<template>
  <aside class="chat" :class="{ compact: props.compact }" data-testid="chat">
    <template v-if="!props.compact">
      <div class="head"><span class="ttl">对话与追问</span></div>
      <div ref="scroller" class="msgs" data-testid="messages">
        <div v-for="m in t.messages" :key="m.id" class="msg" :class="[m.role, m.kind]">
          <div v-if="m.role === 'user'" class="tag">调度指令</div>
          <div v-else-if="m.role === 'answer'" class="tag">你的回答</div>
          {{ m.text }}
        </div>

        <div v-for="q in questions" :key="q.id" class="ask" :data-testid="'ask-' + q.field" :data-qid="q.id">
          <div class="tag">需要你确认</div>
          <div class="qtext">{{ q.text }}</div>
          <div v-if="q.basis" class="basis">推断：{{ q.basis }}</div>

          <template v-if="q.field === 'periods'">
            <div class="opts grid">
              <button v-for="o in q.options" :key="o.value" class="opt" :class="{ on: (picked[q.id] ?? []).includes(o.value), all: o.value === '__all__' }"
                :data-value="o.value" :disabled="t.busy" @click="toggle(q, o.value)">{{ o.label }}</button>
            </div>
            <div class="row" style="margin-top: 6px">
              <el-button size="small" type="primary" :disabled="!(picked[q.id] ?? []).length || t.busy" data-testid="submit-periods" @click="submitPicked(q)">确定所选时段</el-button>
            </div>
          </template>
          <template v-else>
            <div v-if="q.options.length" class="opts">
              <el-tooltip v-for="o in q.options" :key="o.value" :content="o.hint ?? ''" :disabled="!o.hint" placement="top">
                <span><button class="opt" :disabled="o.disabled || t.busy" :data-value="o.value" @click="choose(q, o.value)">{{ o.label }}</button></span>
              </el-tooltip>
            </div>
          </template>

          <div v-if="q.allow_free_text && (q.field === 'periods' || q.field !== 'value' || showManual[q.id] || !q.options.length)" class="free row">
            <el-input v-model="manual[q.id]" size="small" :placeholder="q.free_text_hint ?? '自由补充'" :data-testid="'free-' + q.field" @keyup.enter="submitManual(q)" />
            <el-button size="small" :disabled="t.busy" :data-testid="'free-submit-' + q.field" @click="submitManual(q)">提交</el-button>
          </div>
        </div>

        <div v-if="t.parse?.suppressed" class="msg system warn">{{ t.parse.suppressed }}</div>
      </div>
    </template>

    <InstructionBuilder v-if="props.compact" class="builder" @apply="fromBuilder" />
    <div class="input">
      <el-input v-model="input" :type="props.compact ? 'text' : 'textarea'" :rows="2" :placeholder="placeholder" data-testid="instruction-input"
        :size="props.compact ? 'large' : 'default'" @keydown.enter.exact.prevent="send" />
      <div class="row" :style="{ marginTop: props.compact ? '0' : '6px' }">
        <el-tooltip content="语音输入：待开发" placement="top">
          <span><el-button :size="props.compact ? 'large' : 'small'" disabled data-testid="voice-btn">语音 <StatusBadge feature="m1.voice" small /></el-button></span>
        </el-tooltip>
        <span v-if="!props.compact" class="grow" />
        <el-button type="primary" :size="props.compact ? 'large' : 'small'" :loading="t.busy" :disabled="!input.trim()" data-testid="send-btn" @click="send">
          {{ hasTask ? '补充并重新解析' : '解析' }}
        </el-button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.chat { width: var(--chat-w); flex: none; display: flex; flex-direction: column; min-height: 0; padding: 14px; gap: 10px; background: var(--c-surface); border: 1px solid var(--c-hairline); border-radius: var(--radius); box-shadow: var(--shadow); }
.chat.compact { width: 100%; flex-direction: column; padding: 0; border: none; background: transparent; box-shadow: none; gap: 12px; }
.chat.compact .input { display: flex; gap: 10px; border: none; padding: 0; }
.chat.compact .input :deep(.el-input) { flex: 1; }
.head { padding-bottom: 8px; border-bottom: 1px solid var(--c-hairline); } .ttl { font-weight: 600; font-size: 15px; }
.msgs { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 8px; padding-right: 2px; }
.msg { padding: 9px 12px; border-radius: 10px; background: var(--c-surface-2); font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.msg.user { background: var(--c-primary-bg); } .msg.answer { background: var(--c-success-bg); }
.msg.warn { background: var(--c-warn-bg); color: var(--c-warn); } .msg.error { background: var(--c-danger-bg); color: var(--c-danger); }
.tag { font-size: 11px; color: var(--c-muted); margin-bottom: 2px; }
.ask { border: 1.5px solid var(--c-primary); background: #fbfdff; border-radius: 10px; padding: 10px 12px; }
.ask .tag { color: var(--c-primary); font-weight: 600; }
.qtext { font-size: 12.5px; line-height: 1.6; margin-bottom: 4px; }
.basis { font-size: 11.5px; color: var(--c-infer); background: var(--c-infer-bg); border-radius: 4px; padding: 2px 8px; margin-bottom: 6px; display: inline-block; }
.opts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.opts.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px; }
.opt { font: inherit; font-size: 11.5px; padding: 5px 9px; border-radius: 6px; border: 1px solid var(--c-border); background: var(--c-surface); cursor: pointer; text-align: left; transition: all 0.12s; }
.opt:hover:not(:disabled) { border-color: var(--c-primary); color: var(--c-primary); }
.opt:disabled { cursor: not-allowed; color: var(--c-faint); background: var(--c-surface-2); }
.opt.on { background: var(--c-primary-bg); border-color: var(--c-primary); color: var(--c-primary-ink); font-weight: 600; }
.opt.all { grid-column: span 2; text-align: center; }
.free { margin-top: 6px; }
.input { border-top: 1px solid var(--c-hairline); padding-top: 10px; }
</style>
