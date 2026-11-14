// 任务 store：当前任务、规格草稿、版本、校验报告与跨组件的“聚焦条目”（规格行 ↔ 公式 ↔ 代码 ↔ 校验 联动）。
import { defineStore } from 'pinia'
import { api, ApiError } from '@/api/client'
import type { CheckReport, EngineOption, Formulas, Marker, Meta, ModelSpec, ScaleInfo, SpecDiff, TaskState } from '@/types/api'
import type { StepState } from '@/components/StepBar.vue'

export interface ChatMsg {
  id: number
  role: 'user' | 'system' | 'answer'
  text: string
  kind?: 'info' | 'warn' | 'error'
}

let msgSeq = 1

export const useTaskStore = defineStore('task', {
  state: () => ({
    meta: null as Meta | null,
    state: null as TaskState | null,
    tab: 'spec' as 'spec' | 'formula' | 'code' | 'check',
    step: 1,
    busy: false,
    error: '' as string,
    messages: [] as ChatMsg[],
    // 设置
    engine: 'demo',
    askEnabled: true,
    maxRounds: 3,
    startTime: '' as string, // 断面起始时刻（ISO，分钟）；空 = 默认
    // 产物
    report: null as CheckReport | null,
    reportVersion: null as number | null,
    formulas: null as Formulas | null,
    scale: null as ScaleInfo | null,
    code: '' as string,
    markers: [] as Marker[],
    codeVersion: null as number | null,
    // 联动
    focus: null as { id: string; from: string; at: number } | null,
    // 其他步骤（里程碑 4）要用的当前版本数据
    viewVersion: null as number | null,
    solverMode: 'mock' as string,
    resultTick: 0,
  }),
  getters: {
    taskId: (s) => s.state?.task.id ?? null,
    spec: (s): ModelSpec | null => s.state?.spec ?? null,
    parse: (s) => s.state?.parse ?? null,
    levelInfo: (s) => s.state?.level ?? null,
    versions: (s) => s.state?.versions ?? [],
    current: (s) => s.state?.current_version ?? null,
    blockers: (s) => s.state?.confirm_blockers ?? [],
    engines: (s): EngineOption[] => s.meta?.engines ?? [],
    hasVersion: (s) => (s.state?.current_version ?? null) !== null,
    stepStates(): StepState[] {
      const st = this.state
      const out: StepState[] = ['idle', 'idle', 'idle', 'idle', 'idle', 'idle', 'idle']
      if (!st) {
        out[0] = 'active'
        return out
      }
      out[0] = 'done'
      const hasSpecItems = !!st.spec && (st.spec.delta_pi.length > 0 || st.spec.structural.length > 0)
      out[1] = hasSpecItems ? 'done' : st.parse && st.parse.questions.length ? 'active' : 'idle'
      const confirmed = st.current_version !== null
      out[2] = confirmed ? (st.draft_dirty ? 'active' : 'done') : hasSpecItems ? 'active' : 'idle'
      if (confirmed) {
        const rep = this.report
        out[3] = rep ? (rep.has_error ? 'error' : 'done') : 'active'
        const vs = st.versions.find((x) => x.version === (this.viewVersion ?? st.current_version))
        if (vs && !vs.has_error) {
          out[4] = vs.solved ? 'done' : this.step === 5 ? 'active' : 'idle'
          if (vs.solved || this.step >= 6) out[5] = this.step === 6 ? 'active' : 'done'
          if (vs.evaluated) out[6] = this.step === 7 ? 'active' : 'done'
          else if (this.step === 7) out[6] = 'active'
          else if (vs.solved || this.step >= 6) out[6] = 'active'    // 求解后即可进入风险评估（评估在打开该步时自动运行）
        }
      }
      return out
    },
  },
  actions: {
    say(text: string, kind: ChatMsg['kind'] = 'info', role: ChatMsg['role'] = 'system') {
      this.messages.push({ id: msgSeq++, role, text, kind })
    },
    async loadMeta() {
      if (!this.meta) this.meta = await api.get<Meta>('/meta')
    },
    fail(e: unknown) {
      const m = e instanceof ApiError ? e.message : (e as Error).message
      this.error = m
      this.say(m, 'error')
      return m
    },
    async run<T>(fn: () => Promise<T>): Promise<T | undefined> {
      this.busy = true
      this.error = ''
      try {
        return await fn()
      } catch (e) {
        this.fail(e)
      } finally {
        this.busy = false
      }
    },
    reset() {
      this.state = null
      this.report = null
      this.reportVersion = null
      this.formulas = null
      this.scale = null
      this.code = ''
      this.markers = []
      this.codeVersion = null
      this.focus = null
      this.messages = []
      this.step = 1
      this.tab = 'spec'
      this.error = ''
    },
    setFocus(id: string | null, from: string) {
      this.focus = id ? { id, from, at: Date.now() } : null
    },

    // ---------------- 任务 / 解析 / 追问
    async start(instruction: string) {
      const text = instruction.trim()
      if (!text) return
      await this.run(async () => {
        await this.loadMeta()
        const isNew = !this.state
        if (isNew) {
          this.state = await api.post<TaskState>('/tasks', {
            instruction: text, engine: this.engine, ask_enabled: this.askEnabled, max_rounds: this.maxRounds,
            start: this.startTime || null,
          })
          this.say(text, 'info', 'user')
          this.state = await api.post<TaskState>(`/tasks/${this.state.task.id}/parse`, {})
        } else {
          this.say(text, 'info', 'user')
          this.state = await api.post<TaskState>(`/tasks/${this.taskId}/parse`, {
            instruction: text, supplement: true, engine: this.engine, ask_enabled: this.askEnabled, max_rounds: this.maxRounds,
          })
        }
        this.afterParse()
      })
    },
    afterParse() {
      const p = this.state?.parse
      if (!p) return
      if (p.fallback_note) this.say(p.fallback_note, 'warn')
      this.say(`已解析（${p.engine_name}，${p.elapsed_ms.toFixed(0)} ms）：判为 ${p.level}。` +
        (p.questions.length ? `还有 ${p.questions.length} 个问题需要你确认。` : p.suppressed ?? ''), 'info')
      this.step = this.state?.spec && (this.state.spec.delta_pi.length || this.state.spec.structural.length) ? 2 : 2
      this.report = null
    },
    async reparse(engine?: string) {
      if (!this.taskId) return
      await this.run(async () => {
        this.state = await api.post<TaskState>(`/tasks/${this.taskId}/parse`, {
          engine: engine ?? this.engine, ask_enabled: this.askEnabled, max_rounds: this.maxRounds,
        })
        this.afterParse()
      })
    },
    async answer(questionId: string, answer: string) {
      if (!this.taskId) return
      await this.run(async () => {
        const q = this.parse?.questions.find((x) => x.id === questionId)
        this.state = await api.post<TaskState>(`/tasks/${this.taskId}/answer`, { question_id: questionId, answer })
        const rec = this.state.parse?.answers.at(-1)
        this.say(`${q?.text ?? ''} → ${rec?.answer ?? answer}`, 'info', 'answer')
        this.report = null
        await this.refreshPreview()
      })
    },
    async saveSpec(spec: ModelSpec) {
      if (!this.taskId) return
      await this.run(async () => {
        this.state = await api.put<TaskState>(`/tasks/${this.taskId}/spec`, spec)
        this.report = null
        await this.refreshPreview()
      })
    },

    // ---------------- 预览（草稿公式 / 规模）
    async refreshPreview() {
      if (!this.taskId || !this.state?.spec) return
      try {
        const r = await api.get<{ formulas: Formulas; scale: ScaleInfo }>(`/tasks/${this.taskId}/draft/preview`)
        this.formulas = r.formulas
        this.scale = r.scale
      } catch {
        /* 预览失败不阻塞 */
      }
    },

    // ---------------- 确认 / 版本
    async confirm(reason?: string) {
      if (!this.taskId) return false
      const r = await this.run(async () => {
        try {
          const out = await api.post<{ state: TaskState; version: any }>(`/tasks/${this.taskId}/confirm`, { change_reason: reason || null })
          this.state = out.state
          return out
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) {
            this.say(e.message, 'warn')
            return undefined
          }
          throw e
        }
      })
      if (!r) return false
      const v = r.version
      this.say(`已确认并生成 v${v.version}：公式、代码、校验已就绪（错误 ${v.counts?.error ?? 0} / 警告 ${v.counts?.warn ?? 0}）。`, v.has_error ? 'error' : 'info')
      this.viewVersion = v.version
      this.step = 4
      this.tab = 'check'
      await this.loadVersionArtifacts(v.version)
      return true
    },
    async loadVersionArtifacts(v: number) {
      if (!this.taskId) return
      const [lx, cd, ck] = await Promise.all([
        api.get<{ formulas: Formulas }>(`/tasks/${this.taskId}/versions/${v}/latex`),
        api.get<{ code: string; markers: Marker[]; scale: ScaleInfo }>(`/tasks/${this.taskId}/versions/${v}/code`),
        api.get<any>(`/tasks/${this.taskId}/versions/${v}`),
      ])
      this.formulas = lx.formulas
      this.code = cd.code
      this.markers = cd.markers
      this.scale = cd.scale
      this.codeVersion = v
      this.report = ck.check
      this.reportVersion = v
    },
    async recheck() {
      if (!this.taskId || this.current === null) return
      await this.run(async () => {
        this.report = await api.post<CheckReport>(`/tasks/${this.taskId}/check`, { version: this.current })
        this.reportVersion = this.current
        this.say(`v${this.current} 重新校验：错误 ${this.report.counts.error} / 警告 ${this.report.counts.warn}`, this.report.has_error ? 'error' : 'info')
      })
    },
    async refreshAfterResult() {
      if (this.taskId) this.state = await api.get<TaskState>(`/tasks/${this.taskId}`)   // 版本摘要里的 solved / evaluated 要刷新
      this.resultTick++
    },
    // ---------------- 一键流程：解析 → （用预设回答补全追问）→ 确认 → 校验 → 求解 → 评估
    async solveAndEvaluate() {
      if (!this.taskId || this.current === null) return false
      const r = await this.run(async () => {
        const j = await api.post<any>(`/tasks/${this.taskId}/solve`, { version: this.current })
        if (j.status === 'running') {
          for (let i = 0; i < 300; i++) {
            await new Promise((x) => setTimeout(x, 400))
            const st = await api.get<any>(`/jobs/${j.id}`)
            if (st.status !== 'running') {
              if (st.status !== 'done') throw new Error(st.error || '求解失败')
              break
            }
          }
        } else if (j.status !== 'done') throw new Error(j.error || '求解失败')
        await api.post(`/tasks/${this.taskId}/evaluate?version=${this.current}`)
        this.state = await api.get<TaskState>(`/tasks/${this.taskId}`)
        this.resultTick++
        return true
      })
      return !!r
    },
    async runScenario(sc: { text: string; answers?: Record<string, string> }) {
      this.reset()
      await this.loadMeta()
      this.busy = true
      try {
        this.state = await api.post<TaskState>('/tasks', {
          instruction: sc.text, engine: this.engine, ask_enabled: true, max_rounds: 9, start: this.startTime || null,
        })
        this.say(sc.text, 'info', 'user')
        this.state = await api.post<TaskState>(`/tasks/${this.taskId}/parse`, {})
        for (let k = 0; k < 6 && this.state.parse?.questions.length; k++) {
          const q = this.state.parse.questions[0]
          const a = sc.answers?.[q.field]
          if (a === undefined) break
          const next: TaskState = await api.post<TaskState>(`/tasks/${this.taskId}/answer`, { question_id: q.id, answer: a })
          this.state = next
          this.say(`${q.text} → ${next.parse?.answers.at(-1)?.answer ?? a}`, 'info', 'answer')
        }
        await this.refreshPreview()
      } catch (e) {
        this.fail(e)
      } finally {
        this.busy = false
      }
    },
    async diff(a: string, b: string) {
      return api.get<SpecDiff>(`/tasks/${this.taskId}/diff?a=${a}&b=${b}`)
    },
    async openTask(tid: string) {
      this.reset()
      await this.loadMeta()
      this.state = await api.get<TaskState>(`/tasks/${tid}`)
      this.say(this.state.task.instruction, 'info', 'user')
      if (this.state.current_version !== null) {
        this.viewVersion = this.state.current_version
        await this.loadVersionArtifacts(this.state.current_version)
        this.step = 4
      } else {
        await this.refreshPreview()
        this.step = 2
      }
    },
  },
})
