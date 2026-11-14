import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { setFeatureTable, type FeatureTable } from '@/features'

export interface Integration {
  id: string
  name: string
  feature: string
  state: 'connected' | 'mock' | 'none'
  state_label: string
  mode: string
  endpoint: string
  detail: string
  request: string
  response: string
}

export interface SnapshotInfo {
  id: string
  file: string
  time: string | null
  time_source?: string
  time_mismatch?: boolean
  counts?: { bus: number; gen: number; branch: number }
  error?: string
}

export interface WindowInfo {
  start: string | null
  periods: number
  step_min: number
  single_snapshot: boolean
  snapshot_ids: string[]
  notes: string[]
  labels: string[]
}

export const useAppStore = defineStore('app', {
  state: () => ({
    featuresVersion: 0,
    integrations: [] as Integration[],
    snapshots: [] as SnapshotInfo[],
    defaultSnapshot: null as string | null,
    window: null as WindowInfo | null,
    backendOk: true,
    loaded: false,
  }),
  actions: {
    async init() {
      try {
        const [feat, ints, snaps] = await Promise.all([
          api.get<FeatureTable>('/features'),
          api.get<{ integrations: Integration[] }>('/integrations'),
          api.get<{ default: string | null; snapshots: SnapshotInfo[] }>('/snapshots'),
        ])
        setFeatureTable(feat)
        this.featuresVersion++
        this.integrations = ints.integrations
        this.snapshots = snaps.snapshots
        this.defaultSnapshot = snaps.default
        this.backendOk = true
        await this.loadWindow()
      } catch {
        this.backendOk = false // 后端没起：功能登记走离线兜底文件
      }
      this.loaded = true
    },
    async loadWindow(start?: string, snapshot?: string) {
      const q = new URLSearchParams()
      if (start) q.set('start', start)
      if (snapshot) q.set('snapshot', snapshot)
      this.window = await api.get<WindowInfo>('/window' + (q.toString() ? `?${q}` : ''))
    },
    async refreshIntegrations() {
      this.integrations = (await api.get<{ integrations: Integration[] }>('/integrations')).integrations
    },
  },
})
