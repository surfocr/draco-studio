import React, { useCallback, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Filter,
  SortAsc,
  SortDesc,
  ZoomIn,
  ZoomOut,
  CheckSquare,
  Square,
  Upload,
  RefreshCw,
  Trash2,
  Flag,
  Check,
  X,
} from 'lucide-react'
import { clsx } from 'clsx'
import { assetsApi } from '@/hooks/useApi'
import { useAssetStore } from '@/stores/useAssetStore'
import { useProjectStore } from '@/stores/useProjectStore'
import { useJobStore } from '@/stores/useJobStore'
import { VirtualGrid } from '@/components/ui/VirtualGrid'
import { DropZone } from '@/components/ui/DropZone'
import { Score } from '@/components/ui/Score'
import type { ReviewState, ShotType } from '@/types/api'
import { useToast } from '@/components/providers/ToastProvider'

const SORT_OPTIONS = [
  { value: 'composite_score', label: 'Score' },
  { value: 'aesthetic_score', label: 'Aesthetic' },
  { value: 'face_quality', label: 'Face Quality' },
  { value: 'technical_quality', label: 'Sharpness' },
  { value: 'imported_at', label: 'Import Date' },
  { value: 'filename', label: 'Filename' },
  { value: 'trueskill_mu', label: 'Rank' },
]

const REVIEW_STATES: Array<{ value: ReviewState | ''; label: string }> = [
  { value: '', label: 'All States' },
  { value: 'pending', label: 'Pending' },
  { value: 'reviewed', label: 'Reviewed' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'flagged', label: 'Flagged' },
]

const SHOT_TYPES: Array<{ value: ShotType | ''; label: string }> = [
  { value: '', label: 'All Shots' },
  { value: 'extreme_closeup', label: 'Extreme Closeup' },
  { value: 'closeup', label: 'Closeup' },
  { value: 'medium', label: 'Medium' },
  { value: 'wide', label: 'Wide' },
  { value: 'full_body', label: 'Full Body' },
]

export function Gallery() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const activeProject = useProjectStore((s) => s.activeProject)
  const addJob = useJobStore((s) => s.addJob)

  const {
    assets,
    total,
    page,
    pageSize,
    hasNext,
    isLoading,
    selectedIds,
    filters,
    sortBy,
    sortDir,
    zoom,
    setAssets,
    setLoading,
    updateAsset,
    removeAsset,
    toggleSelect,
    selectAll,
    clearSelection,
    setFilter,
    clearFilters,
    setSortBy,
    toggleSort,
    setZoom,
    setPage,
  } = useAssetStore()

  // Fetch assets
  const { data, isFetching, refetch } = useQuery({
    queryKey: ['assets', activeProject?.id, page, pageSize, sortBy, sortDir, filters],
    queryFn: () =>
      assetsApi.list(activeProject!.id, {
        page,
        page_size: pageSize,
        sort_by: sortBy,
        sort_dir: sortDir,
        ...filters,
      }),
    enabled: !!activeProject?.id,
    placeholderData: (prev) => prev,
  })

  useEffect(() => {
    if (data) {
      setAssets(data.items, data.total, data.has_next)
    }
  }, [data, setAssets])

  useEffect(() => {
    setLoading(isFetching)
  }, [isFetching, setLoading])

  // Mutations
  const updateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Parameters<typeof assetsApi.update>[1] }) =>
      assetsApi.update(id, patch),
    onSuccess: (updated) => {
      updateAsset(updated.id, updated)
      queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
  })

  const ingestMutation = useMutation({
    mutationFn: (files: File[]) => assetsApi.ingestUpload(activeProject!.id, files),
    onSuccess: (result) => {
      toast.success(`Importing ${result.file_count} files…`)
      // Poll for job completion
      setTimeout(() => refetch(), 2000)
    },
    onError: () => toast.error('Failed to start import'),
  })

  const bulkMutation = useMutation({
    mutationFn: ({ action, ids }: { action: string; ids: string[] }) =>
      assetsApi.bulkAction(activeProject!.id, action, ids),
    onSuccess: (result) => {
      toast.success(`${result.affected} assets ${result.action}d`)
      clearSelection()
      refetch()
    },
  })

  const handleApprove = useCallback(
    (id: string) => updateMutation.mutate({ id, patch: { review_state: 'approved' } }),
    [updateMutation]
  )
  const handleReject = useCallback(
    (id: string) => updateMutation.mutate({ id, patch: { is_rejected: true, review_state: 'rejected' } }),
    [updateMutation]
  )
  const handleFlag = useCallback(
    (id: string) => updateMutation.mutate({ id, patch: { is_flagged: true } }),
    [updateMutation]
  )

  const handleSelect = useCallback(
    (id: string, multi: boolean, _range: boolean) => {
      if (multi) {
        toggleSelect(id)
      } else {
        // Single select — just toggle
        toggleSelect(id)
      }
    },
    [toggleSelect]
  )

  const selectedCount = selectedIds.size

  if (!activeProject) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-text-secondary">
        <div className="text-6xl opacity-20">📁</div>
        <p className="text-lg font-medium text-text-primary">No project selected</p>
        <p className="text-sm">Create or select a project to get started</p>
      </div>
    )
  }

  return (
    <DropZone
      onFiles={(files) => ingestMutation.mutate(files)}
      className="flex flex-col h-full"
    >
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-surface shrink-0 flex-wrap">
        {/* Sort */}
        <div className="flex items-center gap-1">
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
            className="text-xs py-1 px-2 w-auto"
            style={{ width: 'auto' }}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            className="btn-ghost btn-icon"
            onClick={() => toggleSort(sortBy)}
            title={sortDir === 'desc' ? 'Descending' : 'Ascending'}
          >
            {sortDir === 'desc' ? <SortDesc size={14} /> : <SortAsc size={14} />}
          </button>
        </div>

        <div className="w-px h-5 bg-border" />

        {/* Filters */}
        <select
          value={filters.review_state ?? ''}
          onChange={(e) => setFilter('review_state', (e.target.value as ReviewState) || undefined)}
          className="text-xs py-1 px-2"
          style={{ width: 'auto' }}
        >
          {REVIEW_STATES.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        <select
          value={filters.shot_type ?? ''}
          onChange={(e) => setFilter('shot_type', (e.target.value as ShotType) || undefined)}
          className="text-xs py-1 px-2"
          style={{ width: 'auto' }}
        >
          {SHOT_TYPES.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        {Object.keys(filters).length > 0 && (
          <button className="btn btn-sm btn-ghost text-text-secondary" onClick={clearFilters}>
            <X size={12} /> Clear
          </button>
        )}

        <div className="flex-1" />

        {/* Stats */}
        <span className="text-xs text-text-secondary">
          {total.toLocaleString()} images
          {selectedCount > 0 && ` · ${selectedCount} selected`}
        </span>

        {/* Zoom */}
        <div className="flex items-center gap-1 border border-border rounded-md overflow-hidden">
          {([0, 1, 2] as const).map((z) => (
            <button
              key={z}
              className={clsx(
                'px-2 py-1 text-xs transition-colors',
                zoom === z
                  ? 'bg-accent text-white'
                  : 'text-text-secondary hover:text-text-primary hover:bg-surface-elevated'
              )}
              onClick={() => setZoom(z)}
              title={['Small', 'Medium', 'Large'][z]}
            >
              {['S', 'M', 'L'][z]}
            </button>
          ))}
        </div>

        {/* Select all */}
        <button
          className="btn-ghost btn-icon"
          onClick={() => selectedCount === assets.length ? clearSelection() : selectAll()}
          title={selectedCount === assets.length ? 'Deselect all' : 'Select all'}
        >
          {selectedCount === assets.length ? (
            <CheckSquare size={15} className="text-accent" />
          ) : (
            <Square size={15} />
          )}
        </button>

        {/* Upload */}
        <label
          htmlFor="file-input-hidden"
          className="btn btn-primary btn-sm cursor-pointer"
        >
          <Upload size={13} />
          Import
        </label>

        {/* Refresh */}
        <button
          className={clsx('btn-ghost btn-icon', isFetching && 'animate-spin')}
          onClick={() => refetch()}
          title="Refresh"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Bulk action bar */}
      {selectedCount > 0 && (
        <div className="flex items-center gap-2 px-3 py-2 bg-accent/10 border-b border-accent/20 text-sm shrink-0">
          <span className="font-medium text-accent">{selectedCount} selected</span>
          <div className="flex-1" />
          <button
            className="btn btn-sm"
            style={{ background: 'rgba(34,197,94,0.15)', color: 'var(--success)', border: '1px solid rgba(34,197,94,0.3)' }}
            onClick={() => bulkMutation.mutate({ action: 'approve', ids: [...selectedIds] })}
          >
            <Check size={12} /> Approve
          </button>
          <button
            className="btn btn-sm"
            style={{ background: 'rgba(245,158,11,0.15)', color: 'var(--warning)', border: '1px solid rgba(245,158,11,0.3)' }}
            onClick={() => bulkMutation.mutate({ action: 'flag', ids: [...selectedIds] })}
          >
            <Flag size={12} /> Flag
          </button>
          <button
            className="btn btn-sm btn-danger"
            onClick={() => bulkMutation.mutate({ action: 'reject', ids: [...selectedIds] })}
          >
            <X size={12} /> Reject
          </button>
          <button className="btn-ghost btn-sm btn" onClick={clearSelection}>
            <X size={12} /> Deselect
          </button>
        </div>
      )}

      {/* Loading indicator */}
      {isLoading && assets.length === 0 && (
        <div className="flex items-center justify-center flex-1 gap-2 text-text-secondary">
          <RefreshCw size={20} className="animate-spin" />
          <span>Loading…</span>
        </div>
      )}

      {/* Grid */}
      <div className="flex-1 overflow-hidden">
        <VirtualGrid
          assets={assets}
          selectedIds={selectedIds}
          zoom={zoom}
          onSelect={handleSelect}
          onApprove={handleApprove}
          onReject={handleReject}
          onFlag={handleFlag}
        />
      </div>
    </DropZone>
  )
}
