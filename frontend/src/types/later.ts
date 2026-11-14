// 步骤 5–7 用到的类型
export interface SolveResult {
  status: 'optimal' | 'feasible' | 'infeasible' | 'error' | 'mock'
  solver: string
  objective: number | null
  periods: number
  timings_s: { read?: number | null; build?: number | null; solve?: number | null; n1_check?: number | null }
  branch_status?: Record<string, number[]>
  gen_p?: Record<string, number[]>
  bus_vm?: Record<string, number[]>
  branch_flow?: Record<string, { pf?: number[]; qf?: number[]; pt?: number[]; qt?: number[] }>
  messages: string[]
}

export interface JobInfo {
  id: string
  status: 'running' | 'done' | 'failed' | 'timeout'
  mode: string
  elapsed_s: number
  error: string | null
  result: SolveResult | null
}

export interface Topo {
  snapshot: string
  nodes: { id: string; bus_i: number; kv: number; type: number; pd: number; vm: number; x: number; y: number }[]
  branches: {
    id: string; row: number; from: string; to: string; kv: number; transformer: boolean; isolating: boolean; in_service: boolean
    parallel: number; rate_a: number; pf: number; qf: number; load_ratio: number | null
  }[]
  kv_levels: number[]
}

export interface Suggestion {
  id: string
  from_code: string
  reason: string
  kind: 'dp' | 's'
  item: any
  fields_needed: string[]
}

export interface Evaluation {
  version: number
  evaluated: boolean
  metrics?: any
  risk?: { risk_level: '低' | '中' | '高'; reasons: { code: string; text: string; level: string }[]; reward: number | null; source: string; mode: string; based_on?: string }
  suggestions?: Suggestion[]
}
