import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, CheckCircle, EyeOff, Layers, Loader2, Trash2 } from 'lucide-react'
import { clsx } from 'clsx'
import { duplicatesApi } from '@/hooks/useApi'
import { useProjectStore } from '@/stores/useProjectStore'
import { useJobStore } from '@/stores/useJobStore'
import { useToast } from '@/components/providers/ToastProvider'
import type {
  DuplicateCluster,
  DuplicateClusterType,
  DuplicateImage,
  DuplicatesResponse,
} from '@/types/api'

type ClusterTypeFilter = 'all' | DuplicateClusterType

const CLUSTER_TYPE_LABELS: Record<DuplicateClusterType, string> = {
  exact: 'Exact',
  phash: 'Perceptual',
  embedding: 'Embedding',
  face: 'Face',
}

const CLUSTER_TYPE_COLORS: Record<DuplicateClusterType, string> = {
  exact: 'text-red-400 bg-red-400/10',
  phash: 'text-orange-400 bg-orange-400/10',
  embedding: 'text-yellow-400 bg-yellow-400/10',
  face: 'text-blue-400 bg-blue-400/10',
}

interface ClusterCardProps {
  cluster: DuplicateCluster
  isSelected: boolean
  onClick: () => void
}

function ClusterCard({ cluster, isSelected, onClick }: ClusterCardProps) {
  const keepCount = cluster.images.filter((image) => image.keep).length

  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full rounded-md border px-3 py-2.5 text-left transition-colors',
        isSelected
          ? 'border-accent bg-accent/20'
          : 'border-border bg-surface hover:bg-surface-elevated'
      )}
    >
      <div className="mb-1 flex items-center justify-between">
        <span
          className={clsx(
            'rounded px-1.5 py-0.5 text-xs font-medium',
            CLUSTER_TYPE_COLORS[cluster.cluster_type]
          )}
        >
          {CLUSTER_TYPE_LABELS[cluster.cluster_type]}
        </span>
        <span className="text-xs text-text-secondary">{cluster.image_count} images</span>
      </div>
      <div className="text-xs text-text-secondary">
        Keep {keepCount} / {cluster.image_count}
      </div>
    </button>
  )
}

interface ImageTileProps {
  image: DuplicateImage
  isBest: boolean
  onToggle: (id: string) => void
}

function ImageTile({ image, isBest, onToggle }: ImageTileProps) {
  return (
    <div
      className={clsx(
        'group relative cursor-pointer overflow-hidden rounded-lg border',
        image.keep ? 'border-green-500' : 'border-border opacity-60'
      )}
      onClick={() => onToggle(image.id)}
    >
      <img src={image.thumbnail_url} alt="" className="aspect-square w-full object-cover" loading="lazy" />

      <div
        className={clsx(
          'absolute inset-0 flex items-center justify-center transition-opacity',
          image.keep ? 'opacity-0 group-hover:opacity-100' : 'opacity-100'
        )}
        style={{ background: image.keep ? 'rgba(0,0,0,0.3)' : 'rgba(0,0,0,0.55)' }}
      >
        {image.keep ? <Trash2 size={20} className="text-white" /> : <CheckCircle size={20} className="text-white" />}
      </div>

      {isBest && (
        <div className="absolute left-1 top-1 rounded bg-green-500 px-1.5 py-0.5 text-xs font-medium text-white">
          Best
        </div>
      )}

      {image.quality_score != null && (
        <div className="absolute bottom-1 right-1 rounded bg-black/60 px-1.5 py-0.5 text-xs text-white">
          {Math.round(image.quality_score * 100)}
        </div>
      )}

      {image.keep && <CheckCircle size={14} className="absolute right-1 top-1 text-green-400" />}
    </div>
  )
}

export function Duplicates() {
  const activeProject = useProjectStore((state) => state.activeProject)
  const addJob = useJobStore((state) => state.addJob)
  const queryClient = useQueryClient()
  const toast = useToast()

  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState<ClusterTypeFilter>('all')
  const [localKeep, setLocalKeep] = useState<Record<string, Record<string, boolean>>>({})

  const { data, isLoading, error } = useQuery<DuplicatesResponse>({
    queryKey: ['duplicates', activeProject?.id],
    queryFn: () => duplicatesApi.list(activeProject!.id),
    enabled: !!activeProject,
  })

  const removeMutation = useMutation({
    mutationFn: (imageIds: string[]) => duplicatesApi.bulkDelete(imageIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['duplicates', activeProject?.id] })
      queryClient.invalidateQueries({ queryKey: ['assets'] })
      toast.success('Removed marked duplicate images')
    },
    onError: (mutationError: Error) => {
      toast.error(mutationError.message || 'Failed to remove duplicates')
    },
  })

  const excludeMutation = useMutation({
    mutationFn: (imageIds: string[]) => duplicatesApi.bulkExclude(activeProject!.id, imageIds),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['assets'] })
      toast.success(`Excluded ${result.excluded} image(s) from export`)
    },
    onError: (mutationError: Error) => {
      toast.error(mutationError.message || 'Failed to exclude duplicates')
    },
  })

  const scanMutation = useMutation({
    mutationFn: () => duplicatesApi.scan(activeProject!.id),
    onSuccess: (result) => {
      addJob({
        id: result.job_id,
        type: 'duplicate_scan',
        status: 'pending',
        progress: 0,
        message: 'Scanning for duplicates',
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
      })
      toast.success('Duplicate scan started')
    },
    onError: (mutationError: Error) => {
      toast.error(mutationError.message || 'Failed to start duplicate scan')
    },
  })

  const filteredClusters = (data?.clusters ?? []).filter(
    (cluster) => typeFilter === 'all' || cluster.cluster_type === typeFilter
  )
  const selectedCluster = filteredClusters.find((cluster) => cluster.id === selectedClusterId) ?? null

  const getEffectiveImages = useCallback(
    (cluster: DuplicateCluster): DuplicateImage[] => {
      const overrides = localKeep[cluster.id] ?? {}
      return cluster.images.map((image) => ({
        ...image,
        keep: image.id in overrides ? overrides[image.id] : image.keep,
      }))
    },
    [localKeep]
  )

  function handleToggle(clusterId: string, imageId: string) {
    setLocalKeep((current) => {
      const cluster = data?.clusters.find((item) => item.id === clusterId)
      if (!cluster) return current

      const clusterOverrides = { ...(current[clusterId] ?? {}) }
      const originalImage = cluster.images.find((image) => image.id === imageId)
      const currentKeep = imageId in clusterOverrides ? clusterOverrides[imageId] : (originalImage?.keep ?? true)
      clusterOverrides[imageId] = !currentKeep

      return { ...current, [clusterId]: clusterOverrides }
    })
  }

  function handleKeepBest(cluster: DuplicateCluster) {
    const overrides = Object.fromEntries(cluster.images.map((image) => [image.id, image.id === cluster.best_id]))
    setLocalKeep((current) => ({ ...current, [cluster.id]: overrides }))
  }

  function handleApplyCluster(cluster: DuplicateCluster) {
    const toRemove = getEffectiveImages(cluster)
      .filter((image) => !image.keep)
      .map((image) => image.id)

    if (toRemove.length === 0) {
      toast.info('No images are marked for removal')
      return
    }

    if (!window.confirm(`Move ${toRemove.length} duplicate image(s) to trash? This can be restored from storage, but the asset records will be removed from the project.`)) {
      return
    }

    removeMutation.mutate(toRemove)
  }

  function handleExcludeCluster(cluster: DuplicateCluster) {
    const toExclude = getEffectiveImages(cluster)
      .filter((image) => !image.keep)
      .map((image) => image.id)

    if (toExclude.length === 0) {
      toast.info('No images are marked for exclusion')
      return
    }

    excludeMutation.mutate(toExclude)
  }

  if (!activeProject) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-text-secondary">
        <Layers size={32} className="opacity-40" />
        <p>Select a project to review duplicates</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-text-secondary">
        <Loader2 size={20} className="animate-spin" />
        <span>Loading duplicate review...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-red-400">
        <AlertCircle size={20} />
        <span>Failed to load duplicates</span>
      </div>
    )
  }

  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex w-64 flex-shrink-0 flex-col border-r border-border bg-surface">
        <div className="border-b border-border px-3 py-3">
          <div className="mb-2 flex items-center gap-2">
            <Layers size={16} className="text-accent" />
            <span className="text-sm font-semibold">Duplicate Clusters</span>
          </div>
          <div className="mb-2 text-xs text-text-secondary">
            {data?.total_clusters ?? 0} clusters - {data?.total_duplicates ?? 0} duplicates
          </div>
          <button
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="btn btn-secondary btn-sm w-full"
          >
            {scanMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Scan for duplicates'}
          </button>
        </div>

        <div className="flex flex-wrap gap-1 border-b border-border px-3 py-2">
          {(['all', 'exact', 'phash', 'embedding', 'face'] as ClusterTypeFilter[]).map((type) => (
            <button
              key={type}
              onClick={() => setTypeFilter(type)}
              className={clsx(
                'rounded px-2 py-0.5 text-xs capitalize',
                typeFilter === type
                  ? 'bg-accent text-white'
                  : 'bg-surface-elevated text-text-secondary hover:text-text-primary'
              )}
            >
              {type}
            </button>
          ))}
        </div>

        <div className="flex-1 space-y-1.5 overflow-y-auto p-2">
          {filteredClusters.length === 0 ? (
            <p className="py-4 text-center text-xs text-text-secondary">
              No duplicate clusters yet. Run a scan to populate this view.
            </p>
          ) : (
            filteredClusters.map((cluster) => (
              <ClusterCard
                key={cluster.id}
                cluster={cluster}
                isSelected={cluster.id === selectedClusterId}
                onClick={() => setSelectedClusterId(cluster.id)}
              />
            ))
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-col overflow-hidden">
        {!selectedCluster ? (
          <div className="flex h-full items-center justify-center gap-2 text-text-secondary">
            <Layers size={24} className="opacity-40" />
            <span>
              {filteredClusters.length === 0
                ? 'Run a scan to find duplicate clusters'
                : 'Select a cluster to review'}
            </span>
          </div>
        ) : (
          <>
            <div className="flex flex-shrink-0 items-center gap-3 border-b border-border bg-surface px-4 py-3">
              <span
                className={clsx(
                  'rounded px-2 py-0.5 text-xs font-medium',
                  CLUSTER_TYPE_COLORS[selectedCluster.cluster_type]
                )}
              >
                {CLUSTER_TYPE_LABELS[selectedCluster.cluster_type]}
              </span>
              <span className="text-sm text-text-secondary">{selectedCluster.image_count} images</span>

              <div className="ml-auto flex gap-2">
                <button
                  onClick={() => handleKeepBest(selectedCluster)}
                  className="flex items-center gap-1.5 rounded-md border border-border bg-surface-elevated px-3 py-1.5 text-xs transition-colors hover:border-accent hover:bg-accent/10"
                >
                  <CheckCircle size={13} />
                  Keep Best
                </button>
                <button
                  onClick={() => handleExcludeCluster(selectedCluster)}
                  disabled={excludeMutation.isPending}
                  className={clsx(
                    'flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors',
                    'border-yellow-500/30 bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20',
                    'disabled:cursor-not-allowed disabled:opacity-50'
                  )}
                  title="Exclude marked images from export (non-destructive)"
                >
                  {excludeMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <EyeOff size={13} />}
                  Exclude
                </button>
                <button
                  onClick={() => handleApplyCluster(selectedCluster)}
                  disabled={removeMutation.isPending}
                  className={clsx(
                    'flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors',
                    'border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20',
                    'disabled:cursor-not-allowed disabled:opacity-50'
                  )}
                  title="Permanently delete marked images from the project"
                >
                  {removeMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                  Delete
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8">
                {getEffectiveImages(selectedCluster).map((image) => (
                  <ImageTile
                    key={image.id}
                    image={image}
                    isBest={image.id === selectedCluster.best_id}
                    onToggle={(imageId) => handleToggle(selectedCluster.id, imageId)}
                  />
                ))}
              </div>

              <div className="mt-4 flex gap-4 text-xs text-text-secondary">
                <span className="flex items-center gap-1">
                  <span className="inline-block h-3 w-3 rounded border border-green-500" />
                  Keep
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block h-3 w-3 rounded border border-border opacity-60" />
                  Remove / Exclude
                </span>
                <span className="ml-2 text-text-secondary/70">
                  Click an image to toggle. <strong>Exclude</strong> hides from export (safe); <strong>Delete</strong> removes permanently.
                </span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default Duplicates
