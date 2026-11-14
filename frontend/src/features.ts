// 功能登记表：状态的唯一来源。
// 与后端 /api/features 同源（backend/app/features.py）；启动时从接口取，
// 取不到（后端没起）时用 features.fallback.json（由 scripts/gen_features.py 从同一份表导出）。
import fallback from './features.fallback.json'

export type FeatureStatus = 'implemented' | 'blackbox' | 'reserved' | 'todo'

export interface Feature {
  id: string
  module: string
  module_name: string
  name: string
  status: FeatureStatus
  status_label: string
  note: string
}

export interface FeatureTable {
  status_labels: Record<FeatureStatus, string>
  modules: Record<string, string>
  features: Feature[]
}

let table: FeatureTable = fallback as FeatureTable

export function setFeatureTable(t: FeatureTable) {
  table = t
}

export function featureTable(): FeatureTable {
  return table
}

export function featureOf(id: string): Feature | undefined {
  return table.features.find((f) => f.id === id)
}

export function statusOf(id: string): FeatureStatus {
  return featureOf(id)?.status ?? 'todo'
}
