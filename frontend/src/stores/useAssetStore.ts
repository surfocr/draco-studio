import { create } from 'zustand'
import type { AssetFilters, AssetSummary, SortDir, SortField } from '@/types/api'

interface AssetState {
  assets: AssetSummary[]
  total: number
  page: number
  pageSize: number
  hasNext: boolean
  isLoading: boolean

  // Selection
  selectedIds: Set<string>

  // Filters + sorting
  filters: AssetFilters
  sortBy: SortField
  sortDir: SortDir
  zoom: 0 | 1 | 2   // 0=small, 1=medium, 2=large

  // Actions
  setAssets: (assets: AssetSummary[], total: number, hasNext: boolean) => void
  setLoading: (v: boolean) => void
  updateAsset: (id: string, patch: Partial<AssetSummary>) => void
  removeAsset: (id: string) => void

  toggleSelect: (id: string) => void
  selectAll: () => void
  clearSelection: () => void
  setSelection: (ids: string[]) => void

  setFilter: <K extends keyof AssetFilters>(key: K, value: AssetFilters[K]) => void
  clearFilters: () => void
  setSortBy: (field: SortField) => void
  setSortDir: (dir: SortDir) => void
  toggleSort: (field: SortField) => void
  setZoom: (zoom: 0 | 1 | 2) => void
  setPage: (page: number) => void
}

const DEFAULT_FILTERS: AssetFilters = {}

export const useAssetStore = create<AssetState>()((set, get) => ({
  assets: [],
  total: 0,
  page: 1,
  pageSize: 50,
  hasNext: false,
  isLoading: false,
  selectedIds: new Set(),
  filters: DEFAULT_FILTERS,
  sortBy: 'imported_at',
  sortDir: 'desc',
  zoom: 1,

  setAssets: (assets, total, hasNext) =>
    set({ assets, total, hasNext, isLoading: false }),
  setLoading: (v) => set({ isLoading: v }),

  updateAsset: (id, patch) =>
    set((s) => ({
      assets: s.assets.map((a) => (a.id === id ? { ...a, ...patch } : a)),
    })),
  removeAsset: (id) =>
    set((s) => ({
      assets: s.assets.filter((a) => a.id !== id),
      selectedIds: new Set([...s.selectedIds].filter((sid) => sid !== id)),
    })),

  toggleSelect: (id) =>
    set((s) => {
      const next = new Set(s.selectedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { selectedIds: next }
    }),
  selectAll: () =>
    set((s) => ({ selectedIds: new Set(s.assets.map((a) => a.id)) })),
  clearSelection: () => set({ selectedIds: new Set() }),
  setSelection: (ids) => set({ selectedIds: new Set(ids) }),

  setFilter: (key, value) =>
    set((s) => ({ filters: { ...s.filters, [key]: value }, page: 1 })),
  clearFilters: () => set({ filters: DEFAULT_FILTERS, page: 1 }),
  setSortBy: (sortBy) => set({ sortBy, page: 1 }),
  setSortDir: (sortDir) => set({ sortDir, page: 1 }),
  toggleSort: (field) =>
    set((s) => ({
      sortBy: field,
      sortDir: s.sortBy === field && s.sortDir === 'desc' ? 'asc' : 'desc',
      page: 1,
    })),
  setZoom: (zoom) => set({ zoom }),
  setPage: (page) => set({ page }),
}))
