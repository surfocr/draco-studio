import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Flag,
  FolderInput,
  RefreshCw,
  SortAsc,
  SortDesc,
  Square,
  Upload,
  X,
} from 'lucide-react'
import { clsx } from 'clsx'
import { assetsApi } from '@/hooks/useApi'
import { useAssetStore } from '@/stores/useAssetStore'
import { useProjectStore } from '@/stores/useProjectStore'
import { useJobStore } from '@/stores/useJobStore'
import { DropZone } from '@/components/ui/DropZone'
import { VirtualGrid } from '@/components/ui/VirtualGrid'
import { AssetDetailPanel } from '@/components/ui/AssetDetailPanel'
import { useToast } from '@/components/providers/ToastProvider'
import type { ReviewState, ShotType } from '@/types/api'
import type { ImportFileCandidate } from '@/lib/importFiles'

const SORT_OPTIONS = [
  { value: 'composite_score', label: 'Score' },
  { value: 'aesthetic_score', label: 'Aesthetic' },
  { value: 'face_quality', label: 'Face Quality' },
  { value: 'technical_quality', label: 'Sharpness' },
  { value: 'imported_at', label: 'Import Date' },
  { value: 'filename', label: 'Filename' },
  { value: 'trueskill_mu', label: 'Rank' },
] as const

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
  const activeProject = useProjectStore((state) => state.activeProject)
  const addJob = useJobStore((state) => state.addJob)

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
    placeholderData: (previous) => previous,
  })

  useEffect(() => {
    if (data) setAssets(data.items, data.total, data.has_next)
  }, [data, setAssets])

  useEffect(() => {
    setLoading(isFetching)
  }, [isFetching, setLoading])

  const updateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Parameters<typeof assetsApi.update>[1] }) =>
      assetsApi.update(id, patch),
    onSuccess: (updated) => {
      updateAsset(updated.id, updated)
      queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to update asset')
    },
  })

  const ingestMutation = useMutation({
    mutationFn: (files: ImportFileCandidate[]) => assetsApi.ingestUpload(activeProject!.id, files),
    onSuccess: (result) => {
      addJob({
        id: result.job_id,
        type: 'ingest_upload',
        status: 'pending',
        progress: 0,
        message: `Importing ${result.file_count} files`,
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
      })
      toast.success(`Import started for ${result.file_count} files`)
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to start import')
    },
  })

  const bulkMutation = useMutation({
    mutationFn: ({ action, ids }: { action: string; ids: string[] }) =>
      assetsApi.bulkAction(activeProject!.id, action, ids),
    onSuccess: (result) => {
      const pastTense =
        result.action === 'reject'
          ? 'rejected'
          : result.action === 'flag'
          ? 'flagged'
          : `${result.action}d`
      toast.success(`${result.affected} assets ${pastTense}`)
      clearSelection()
      refetch()
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Bulk action failed')
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

  const [detailAssetId, setDetailAssetId] = useState<string | null>(null)
  const [showPathImport, setShowPathImport] = useState(false)
  const [importPath, setImportPath] = useState('')
  const [importRecursive, setImportRecursive] = useState(true)
  const pathInputRef = useRef<HTMLInputElement>(null)

  const ingestDirectoryMutation = useMutation({
    mutationFn: (path: string) =>
      assetsApi.ingestDirectory(activeProject!.id, path, importRecursive),
    onSuccess: (result) => {
      addJob({
        id: result.job_id,
        type: 'ingest_directory',
        status: 'pending',
        progress: 0,
        message: `Importing from folder…`,
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
      })
      toast.success('Folder import started')
      setShowPathImport(false)
      setImportPath('')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to start folder import')
    },
  })

  const handlePathImportSubmit = () => {
    const trimmed = importPath.trim()
    if (!trimmed) return
    ingestDirectoryMutation.mutate(trimmed)
  }

  const handleSelect = useCallback(
    (id: string, multi: boolean, _range: boolean) => {
      if (multi) {
        toggleSelect(id)
      } else {
        // Single click: open detail panel
        setDetailAssetId((prev) => (prev === id ? null : id))
      }
    },
    [toggleSelect]
  )

  const detailIndex = detailAssetId ? assets.findIndex((a) => a.id === detailAssetId) : -1

  const handleDetailPrev = useCallback(() => {
    if (detailIndex > 0) setDetailAssetId(assets[detailIndex - 1].id)
  }, [detailIndex, assets])

  const handleDetailNext = useCallback(() => {
    if (detailIndex >= 0 && detailIndex < assets.length - 1) setDetailAssetId(assets[detailIndex + 1].id)
  }, [detailIndex, assets])

  const selectedCount = selectedIds.size
  const allSelected = assets.length > 0 && selectedCount === assets.length

  if (!activeProject) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 text-text-secondary">
        <div className="text-center">
          <p className="text-lg font-medium text-text-primary">No project selected</p>
          <p className="mt-1 text-sm">Create a project in Settings, then import images to begin curation.</p>
        </div>
        <Link to="/settings" className="btn btn-primary btn-sm">
          Create Project
        </Link>
      </div>
    )
  }

  return (
    <DropZone onFiles={(files) => ingestMutation.mutate(files)} className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-2">
        <div className="flex items-center gap-1">
          <select
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value as typeof sortBy)}
            className="w-auto px-2 py-1 text-xs"
            style={{ width: 'auto' }}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
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

        <div className="h-5 w-px bg-border" />

        <select
          value={filters.review_state ?? ''}
          onChange={(event) => setFilter('review_state', (event.target.value as ReviewState) || undefined)}
          className="px-2 py-1 text-xs"
          style={{ width: 'auto' }}
        >
          {REVIEW_STATES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        <select
          value={filters.shot_type ?? ''}
          onChange={(event) => setFilter('shot_type', (event.target.value as ShotType) || undefined)}
          className="px-2 py-1 text-xs"
          style={{ width: 'auto' }}
        >
          {SHOT_TYPES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        {Object.keys(filters).length > 0 && (
          <button className="btn btn-ghost btn-sm text-text-secondary" onClick={clearFilters}>
            <X size={12} />
            Clear
          </button>
        )}

        <div className="flex-1" />

        <span className="text-xs text-text-secondary">
          {total.toLocaleString()} images
          {selectedCount > 0 && ` - ${selectedCount} selected`}
        </span>

        <div className="overflow-hidden rounded-md border border-border">
          {([0, 1, 2] as const).map((value) => (
            <button
              key={value}
              onClick={() => setZoom(value)}
              className={clsx(
                'px-2 py-1 text-xs transition-colors',
                zoom === value
                  ? 'bg-accent text-white'
                  : 'text-text-secondary hover:bg-surface-elevated hover:text-text-primary'
              )}
              title={['Small', 'Medium', 'Large'][value]}
            >
              {['S', 'M', 'L'][value]}
            </button>
          ))}
        </div>

        <button
          className="btn-ghost btn-icon"
          onClick={() => (allSelected ? clearSelection() : selectAll())}
          title={allSelected ? 'Deselect all' : 'Select all'}
        >
          {allSelected ? <CheckSquare size={15} className="text-accent" /> : <Square size={15} />}
        </button>

        <label htmlFor="file-input-hidden" className="btn btn-primary btn-sm cursor-pointer">
          <Upload size={13} />
          Import
        </label>

        <label htmlFor="folder-input-hidden" className="btn btn-secondary btn-sm cursor-pointer">
          <Upload size={13} />
          Import Folder
        </label>

        <button
          className="btn btn-secondary btn-sm"
          title="Import images from a folder path on this machine (server-side, no browser memory limit)"
          onClick={() => {
            setShowPathImport(true)
            setTimeout(() => pathInputRef.current?.focus(), 50)
          }}
        >
          <FolderInput size={13} />
          Import by Path
        </button>

        <button
          className={clsx('btn-ghost btn-icon', isFetching && 'animate-spin')}
          onClick={() => refetch()}
          title="Refresh"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Import by path dialog */}
      {showPathImport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-md rounded-lg border border-border bg-surface p-5 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold">Import Folder by Path</h2>
              <button
                className="btn-ghost btn-icon"
                onClick={() => setShowPathImport(false)}
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>
            <p className="mb-3 text-sm text-text-secondary">
              Enter the full path to a folder on this machine. The server reads images
              directly — no upload size limits.
            </p>
            <label className="mb-1 block text-xs font-medium text-text-secondary">
              Folder path
            </label>
            <input
              ref={pathInputRef}
              type="text"
              className="input mb-3 w-full font-mono text-sm"
              placeholder="C:\Users\you\Pictures\dataset  or  /home/you/pictures/dataset"
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handlePathImportSubmit()
                if (e.key === 'Escape') setShowPathImport(false)
              }}
            />
            <label className="mb-4 flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="checkbox"
                checked={importRecursive}
                onChange={(e) => setImportRecursive(e.target.checked)}
              />
              Include sub-folders (recursive)
            </label>
            <div className="flex justify-end gap-2">
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setShowPathImport(false)}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary btn-sm"
                disabled={!importPath.trim() || ingestDirectoryMutation.isPending}
                onClick={handlePathImportSubmit}
              >
                {ingestDirectoryMutation.isPending ? 'Starting…' : 'Start Import'}
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedCount > 0 && (
        <div className="flex flex-shrink-0 items-center gap-2 border-b border-accent/20 bg-accent/10 px-3 py-2 text-sm">
          <span className="font-medium text-accent">{selectedCount} selected</span>
          <div className="flex-1" />
          <button
            className="btn btn-sm"
            style={{
              background: 'rgba(34,197,94,0.15)',
              color: 'var(--success)',
              border: '1px solid rgba(34,197,94,0.3)',
            }}
            onClick={() => bulkMutation.mutate({ action: 'approve', ids: [...selectedIds] })}
          >
            <Check size={12} />
            Approve
          </button>
          <button
            className="btn btn-sm"
            style={{
              background: 'rgba(245,158,11,0.15)',
              color: 'var(--warning)',
              border: '1px solid rgba(245,158,11,0.3)',
            }}
            onClick={() => bulkMutation.mutate({ action: 'flag', ids: [...selectedIds] })}
          >
            <Flag size={12} />
            Flag
          </button>
          <button className="btn btn-danger btn-sm" onClick={() => bulkMutation.mutate({ action: 'reject', ids: [...selectedIds] })}>
            <X size={12} />
            Reject
          </button>
          <button className="btn btn-ghost btn-sm" onClick={clearSelection}>
            <X size={12} />
            Deselect
          </button>
        </div>
      )}

      {isLoading && assets.length === 0 ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-text-secondary">
          <RefreshCw size={20} className="animate-spin" />
          <span>Loading...</span>
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden">
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
          {detailAssetId && (
            <AssetDetailPanel
              assetId={detailAssetId}
              onClose={() => setDetailAssetId(null)}
              onApprove={handleApprove}
              onReject={handleReject}
              onFlag={handleFlag}
              onPrev={handleDetailPrev}
              onNext={handleDetailNext}
              hasPrev={detailIndex > 0}
              hasNext={detailIndex < assets.length - 1}
            />
          )}
        </div>
      )}

      {total > pageSize && (
        <div className="flex flex-shrink-0 items-center justify-center gap-3 border-t border-border bg-surface px-3 py-2">
          <button
            className="btn-ghost btn-icon"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            title="Previous page"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="tabular-nums text-xs text-text-secondary">
            Page {page} of {Math.ceil(total / pageSize)}
          </span>
          <button
            className="btn-ghost btn-icon"
            disabled={!hasNext}
            onClick={() => setPage(page + 1)}
            title="Next page"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </DropZone>
  )
}
