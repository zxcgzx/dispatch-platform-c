<script setup lang="ts">
// 建模工作台（向导式）：顶部步骤条 + 一个主按钮推进；左栏对话与追问；右栏随步骤切换。
// 为了不繁琐：首页直接给出“演示场景”卡片，一键跑完 指令 → 建模 → 校验 → 求解 → 评估；
// 公式 / 代码 / 校验 / 版本这些进阶内容放在“规格确认”页的标签里，需要时再看。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useTaskStore } from '@/stores/task'
import StepBar from '@/components/StepBar.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import LevelPanel from '@/components/LevelPanel.vue'
import SpecEditor from '@/components/SpecEditor.vue'
import FormulaView from '@/components/FormulaView.vue'
import CodeView from '@/components/CodeView.vue'
import CheckView from '@/components/CheckView.vue'
import VersionBar from '@/components/VersionBar.vue'
import DataDrawer from '@/components/DataDrawer.vue'
import SolvePanel from '@/components/SolvePanel.vue'
import ResultPanel from '@/components/ResultPanel.vue'
import RiskPanel from '@/components/RiskPanel.vue'

const app = useAppStore()
const t = useTaskStore()
const route = useRoute()
const embed = computed(() => !!route.meta.embed)
const win = computed(() => app.window)
const dataOpen = ref(false)
const settingsOpen = ref(false)
const running = ref(false)

onMounted(async () => {
  await Promise.all([app.init(), t.loadMeta()])
})

const engineValue = computed({
  get: () => t.engine,
  set: (v: string) => {
    t.engine = v
    if (t.taskId) void t.reparse(v)
  },
})
const selectedEngine = computed(() => t.engines.find((e) => e.id === t.engine))
const scenarios = computed(() => t.meta?.scenarios ?? [])
const levelColor: Record<string, string> = { L1: '#2a9d4a', L2: '#c98a00', L3: '#1f5fc4', L4: '#8c1515' }

function goStep(n: number) {
  t.step = n
  if (n === 3) t.tab = 'spec'
  if (n === 4) t.tab = 'check'
}
const stepsRight = computed(() => (t.step <= 2 ? 'level' : t.step <= 4 ? 'tabs' : 'later'))
const canNext = computed(() => t.hasVersion && !t.report?.has_error)
const period = computed(() => (win.value ? (win.value.periods === 1 ? '单时段断面' : `${win.value.periods} 时段 × ${win.value.step_min} 分钟`) : '单时段断面'))

// ---- 演示场景：一键从指令走到评估
async function runScenario(sc: any, full = true) {
  if (running.value) return
  running.value = true
  try {
    await t.runScenario(sc)
    if (!full || t.parse?.questions.length || !t.state) {
      t.step = 2
      return
    }
    t.step = 3
    const ok = await t.confirm()
    if (!ok) return
    if (t.report?.has_error) return
    t.say('正在求解（内置 HiGHS，直流近似 OTS）…', 'info')
    const solved = await t.solveAndEvaluate()
    if (solved) {
      t.say('求解完成，已计算指标与风险。', 'info')
      t.step = 6
    }
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    running.value = false
  }
}
function newTask() { t.reset() }

// ---- 主按钮（跟随步骤）
const primary = computed(() => {
  if (!t.state) return null
  if (t.step <= 2) return { text: '确认建模规格 →', go: () => goStep(3) }
  if (t.step === 3 && !t.hasVersion) return null
  if (t.step === 3 || t.step === 4) return { text: '求解并评估 →', disabled: !canNext.value, go: async () => { running.value = true; const ok = await t.solveAndEvaluate(); running.value = false; if (ok) t.step = 6 } }
  if (t.step === 5) return { text: '查看结果 →', go: () => (t.step = 6) }
  if (t.step === 6) return { text: '风险评估 →', go: () => (t.step = 7) }
  return null
})
</script>

<template>
  <div class="wb" data-testid="workbench">
    <section class="topbar">
      <div class="row grow" style="gap: 18px">
        <span v-if="embed" class="brand">方式调整智能体平台 · 课题 4</span>
        <div class="chip-info" data-testid="snapshot-bar">
          <span class="k">数据断面</span><b>大理 905 节点</b>
          <span class="dot-sep" />
          <b data-testid="window-label">{{ period }}</b>
          <el-tag v-if="win?.single_snapshot" size="small" effect="plain" type="info" data-testid="demo-tag">单断面</el-tag>
        </div>
      </div>
      <el-popover v-model:visible="settingsOpen" placement="bottom-end" :width="340" trigger="click">
        <template #reference><el-button size="small" data-testid="settings-btn">设置</el-button></template>
        <div class="settings">
          <label>建模引擎
            <el-select v-model="engineValue" size="small" data-testid="engine-select">
              <el-option v-for="e in t.engines" :key="e.id" :value="e.id" :label="e.label" :disabled="!e.selectable">
                <span>{{ e.label }}</span>
                <span v-if="!e.selectable" class="sub" style="margin-left: 8px"><StatusBadge :feature="e.feature" small /></span>
                <span v-else-if="!e.configured" class="sub" style="margin-left: 8px">未配置</span>
              </el-option>
            </el-select>
          </label>
          <div v-if="selectedEngine && !selectedEngine.configured" class="sub warn-line">未配置，将自动回落到演示规则引擎</div>
          <label>追问
            <span class="row"><el-switch v-model="t.askEnabled" size="small" data-testid="ask-switch" />
              <span class="sub">最多</span><el-input-number v-model="t.maxRounds" size="small" :min="0" :max="9" :disabled="!t.askEnabled" style="width: 86px" data-testid="max-rounds" /><span class="sub">轮</span></span>
          </label>
        </div>
      </el-popover>
      <el-button size="small" data-testid="data-btn" @click="dataOpen = true">数据概况</el-button>
      <el-button v-if="t.state" size="small" type="primary" plain data-testid="new-task" @click="newTask">新任务</el-button>
    </section>

    <StepBar v-if="t.state" :states="t.stepStates" :current="t.step" @go="goStep" />

    <!-- 首页：场景卡片 -->
    <div v-if="!t.state" class="home" data-testid="home">
      <div class="hero">
        <h1>用一句话，调整电网运行方式</h1>
        <p>输入调度指令，系统自动判定层级、生成数学模型、校验去幻觉、求解并评估风险。下面任选一个场景，一键走完整个流程。</p>
      </div>
      <div class="scs" data-testid="scenarios">
        <button v-for="sc in scenarios" :key="sc.id" class="sc" :data-scenario="sc.id" :disabled="running" @click="runScenario(sc)">
          <span class="lv" :style="{ background: levelColor[sc.level] }">{{ sc.level }}</span>
          <b>{{ sc.title }}</b>
          <span class="desc">{{ sc.desc }}</span>
          <span class="cmd">“{{ sc.text }}”</span>
          <span class="go">{{ running ? '运行中…' : '一键演示 →' }}</span>
        </button>
      </div>
      <div class="or">或者自己组一句指令：选对象和动作，或直接输入</div>
    </div>

    <div v-if="!t.state" class="flowline" data-testid="flowline">
      <div v-for="(s, i) in ['指令输入', '层级判定', '规格确认', '去幻觉校验', '求解', '结果与地图', '风险评估']" :key="s" class="fl">
        <i>{{ i + 1 }}</i><span>{{ s }}</span>
      </div>
    </div>
    <div class="body" :class="{ idle: !t.state }">
      <ChatPanel :compact="!t.state" />
      <section v-if="t.state" class="right" data-testid="right-pane">
        <template v-if="stepsRight === 'level'">
          <LevelPanel />
        </template>
        <template v-else-if="stepsRight === 'tabs'">
          <el-tabs v-model="t.tab" data-testid="main-tabs">
            <el-tab-pane label="规格" name="spec"><SpecEditor /></el-tab-pane>
            <el-tab-pane label="公式" name="formula"><FormulaView /></el-tab-pane>
            <el-tab-pane label="代码" name="code"><CodeView /></el-tab-pane>
            <el-tab-pane label="校验" name="check"><CheckView /></el-tab-pane>
          </el-tabs>
        </template>
        <template v-else>
          <SolvePanel v-if="t.step === 5" :key="'s' + t.viewVersion" />
          <ResultPanel v-else-if="t.step === 6" :key="'r' + t.viewVersion + '-' + t.resultTick" />
          <RiskPanel v-else-if="t.step === 7" :key="'k' + t.viewVersion + '-' + t.resultTick" />
        </template>
        <div v-if="primary" class="dock">
          <span v-if="t.step === 4 && t.report?.has_error" class="lv-error">校验有错误，不能求解：请回到“规格”修正。</span>
          <span v-else-if="t.step === 4 && t.report?.has_warning" class="lv-warn">有警告：确认无误后继续。</span>
          <span class="grow" />
          <el-button type="primary" size="large" :disabled="primary.disabled || running" :loading="running" data-testid="primary-btn" @click="primary.go">{{ primary.text }}</el-button>
        </div>
      </section>
    </div>
    <VersionBar v-if="t.state" />
    <DataDrawer v-model="dataOpen" />
  </div>
</template>

<style scoped>
.wb { height: 100%; display: flex; flex-direction: column; gap: 12px; padding: 14px 24px 12px; min-height: 0; background: var(--c-bg); }
.topbar { display: flex; align-items: center; gap: 10px; flex: none; }
.brand { font-weight: 700; color: var(--c-brand-blue); }
.chip-info { display: inline-flex; align-items: center; gap: 8px; background: var(--c-surface); border: 1px solid var(--c-hairline); border-radius: 18px; padding: 5px 14px; font-size: 13px; box-shadow: var(--shadow); }
.chip-info .k { color: var(--c-muted); }
.dot-sep { width: 4px; height: 4px; border-radius: 50%; background: var(--c-faint); }
.body { flex: 1; min-height: 0; display: flex; gap: 14px; }
.body.idle { flex: none; }
.right { flex: 1; min-width: 0; overflow: auto; position: relative; display: flex; flex-direction: column; }
.right > :not(.dock) { flex: none; }
.dock { margin-top: 14px; flex: none; display: flex; align-items: center; gap: 12px; padding: 12px 18px; background: rgba(255, 255, 255, 0.96); backdrop-filter: blur(6px); border: 1px solid var(--c-hairline); border-radius: var(--radius); box-shadow: var(--shadow); }
.settings { display: flex; flex-direction: column; gap: 12px; } .settings label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--c-muted); }
.warn-line { color: var(--c-warn); }
.home { flex: none; }
.hero { background: var(--grad-hero); color: #fff; border-radius: 14px; padding: 26px 34px; position: relative; overflow: hidden; }
.hero::after { content: ''; position: absolute; right: -60px; top: -80px; width: 320px; height: 320px; border-radius: 50%; background: radial-gradient(circle, rgba(255, 255, 255, 0.16), transparent 65%); }
.hero h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: 2px; }
.hero p { margin: 0; opacity: 0.88; font-size: 14px; max-width: 720px; line-height: 1.7; }
.scs { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-top: 14px; }
.sc { text-align: left; font: inherit; cursor: pointer; background: var(--c-surface); border: 1px solid var(--c-hairline); border-radius: 12px; padding: 16px 18px; display: flex; flex-direction: column; gap: 6px; box-shadow: var(--shadow); transition: transform 0.15s, box-shadow 0.15s, border-color 0.15s; position: relative; }
.sc:hover:not(:disabled) { transform: translateY(-3px); border-color: var(--c-primary); box-shadow: 0 10px 28px rgba(31, 95, 196, 0.16); }
.sc:disabled { opacity: 0.6; cursor: wait; }
.sc b { font-size: 16px; color: var(--c-ink); }
.lv { align-self: flex-start; color: #fff; font-size: 11px; font-weight: 700; padding: 1px 9px; border-radius: 10px; letter-spacing: 1px; }
.desc { font-size: 12.5px; color: var(--c-muted); line-height: 1.6; }
.cmd { font-size: 12px; color: var(--c-primary-ink); background: var(--c-primary-bg); border-radius: 6px; padding: 5px 9px; line-height: 1.6; }
.go { margin-top: 4px; font-size: 13px; color: var(--c-primary); font-weight: 600; }
.or { text-align: center; color: var(--c-faint); font-size: 12px; margin-top: 6px; }
.flowline { display: flex; justify-content: center; align-items: center; gap: 0; margin-top: 26px; }
.fl { display: flex; align-items: center; gap: 8px; color: var(--c-muted); font-size: 13px; position: relative; padding: 0 18px; }
.fl i { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font-style: normal; font-weight: 700; font-size: 12px; background: var(--c-primary-bg); color: var(--c-primary-ink); }
.fl:not(:last-child)::after { content: ''; position: absolute; right: -14px; top: 50%; width: 28px; height: 1px; background: var(--c-border); }
</style>
