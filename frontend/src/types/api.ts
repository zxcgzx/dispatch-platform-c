// 后端 API 的响应类型。规格本身（ModelSpec 等）由 JSON Schema 生成，见 spec.generated.ts；这里只补接口层。
import type { ModelSpec, DeltaPi1, StructuralOp, BaseModelDef, SolverReq } from './spec.generated'

export type { ModelSpec, BaseModelDef, SolverReq, StructuralOp }
export type DeltaPi = DeltaPi1

export interface Entity {
  id: string
  type: 'bus' | 'branch' | 'gen' | 'period' | 'kv' | 'keyword'
  text: string
  start: number
  end: number
  object_id: string | null
  status: 'found' | 'not_found' | 'ambiguous' | 'ok' | 'fuzzy'
  candidates: string[]
  periods: number[] | null
  kv: number | null
  role: string | null
  note: string | null
  item_ids: string[]
}

export interface Option {
  label: string
  value: string
  disabled: boolean
  hint: string | null
}

export interface Question {
  id: string
  field: 'target' | 'periods' | 'value' | 'beta' | 'other'
  item_id: string | null
  param: string | null
  text: string
  options: Option[]
  multi: boolean
  allow_free_text: boolean
  free_text_hint: string | null
  basis: string | null
  blocking: boolean
}

export interface PendingIntent {
  id: string
  component: 'bus' | 'gen' | 'branch'
  param: string
  evidence: string
  candidates: string[]
  label: string
  source: 'explicit' | 'inferred'
}

export interface ParseResult {
  instruction: string
  entities: Entity[]
  delta_pi: DeltaPi[]
  structural: StructuralOp[]
  omega_confirm: { n_minus_1?: boolean; evidence?: string }
  pending: PendingIntent[]
  unresolved: Record<string, string[]>
  questions: Question[]
  notes: string[]
  answers: { question_id: string; question: string; answer: string; raw: string }[]
  evidence_spans: Record<string, [number, number]>
  level: string
  engine: string
  engine_name: string
  elapsed_ms: number
  fallback_note: string | null
  rounds: number
  suppressed: string | null
}

export interface LevelInfo {
  level: string
  display: string
  overridden: boolean
  inferred: string[]
  structural: string[]
  text: string
}

export interface VersionSummary {
  version: number
  parent_version: number | null
  change_reason: string | null
  created_at: string
  level: string
  checked: boolean
  has_error: boolean
  has_warning: boolean
  counts: { error: number; warn: number; info: number } | null
  solved: boolean
  evaluated: boolean
}

export interface TaskState {
  task: {
    id: string
    created_at: string
    instruction: string
    snapshot_id: string
    start: string | null
    engine: string
    ask_enabled: boolean
    max_rounds: number
    feedback_mode: string
  }
  parse: ParseResult | null
  spec: ModelSpec | null
  level: LevelInfo | null
  versions: VersionSummary[]
  current_version: number | null
  draft_dirty: boolean
  confirm_blockers: string[]
  draft_parent: number | null
  draft_change_reason: string | null
}

export interface Finding {
  layer: number
  code: string
  level: 'error' | 'warn' | 'info'
  message: string
  item_id: string | null
  suggestion: string | null
  source: string
  data: any
}

export interface CheckLayer {
  layer: number
  name: string
  status: 'red' | 'yellow' | 'green'
  findings: Finding[]
}

export interface CheckReport {
  level: string
  layers: CheckLayer[]
  has_error: boolean
  has_warning: boolean
  counts: { error: number; warn: number; info: number }
  external: { state: string; label: string }
  build: any
}

export interface FormulaChange {
  id: string
  kind: 'dp' | 's'
  title: string
  latex: string
  inferred: boolean
  confirmed: boolean
  pending: boolean
  affects: string[]
  custom?: boolean
}

export interface FormulaBlock {
  id: string
  title: string
  latex: string
  note: string | null
  abstract: boolean
  highlight: boolean
  changed_by: string[]
}

export interface Formulas {
  objective: { id: string; title: string; latex: string; pending: boolean; note: string | null; terms: any[] }
  changes: FormulaChange[]
  blocks: FormulaBlock[]
  new_blocks: { id: string; title: string; latex: string; custom: boolean; kind: string }[]
  fixed_topology: boolean
  symbols: string
}

export interface ScaleInfo {
  T: number
  buses: number
  gens: number
  branches: number
  switchable: number
  vars_continuous: number
  vars_binary: number
  vars_total: number
  constraints: number
  by_rule: Record<string, { name: string; branches: number; binary_vars: number; current: boolean }>
  blocks: { id: string; title: string; vars_cont: number; vars_bin: number; cons: number; note: string }[]
  note: string
  fixed_topology: boolean
}

export interface Marker {
  id: string
  title: string
  start: number
  end: number
  custom: boolean
  pending: boolean
}

export interface EngineOption {
  id: string
  label: string
  selectable: boolean
  configured: boolean
  feature: string
  note: string
}

export interface Meta {
  engines: EngineOption[]
  whitelist: Record<string, Record<string, { ops: string[]; dirs: string[]; label: string; unit: string }>>
  operators: Record<string, { name: string; kind: string; meaning: string; params: Record<string, any> }>
  rules: { switchable_rules: Record<string, string>; contingency_rules: Record<string, string> }
  questions: { ask_enabled: boolean; max_rounds: number }
  templates: { id: string; label: string; text: string }[]
  scenarios: { id: string; title: string; level: string; icon: string; desc: string; text: string; answers: Record<string, string> }[]
}

export interface SpecDiff {
  a: number | null
  b: number | null
  delta_pi: DiffGroup
  structural: DiffGroup
  omega: { field: string; a: any; b: any }[]
  solver_req: { field: string; a: any; b: any }[]
  instruction_changed: boolean
  instruction_a: string
  instruction_b: string
  change_reason_b: string | null
  total: number
}

export interface DiffGroup {
  added: { key: string; id: string; item: any }[]
  removed: { key: string; id: string; item: any }[]
  modified: { key: string; id_a: string; id_b: string; changes: { field: string; a: any; b: any }[] }[]
}
