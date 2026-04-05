// frontend/src/views/Duplicates.tsx
// Duplicate image cluster browser — review clusters, keep/remove per image

import React, { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Layers, Trash2, CheckCircle, ChevronDown, ChevronUp, Loader2, AlertCircle } from 'lucide-react'
import { clsx } from 'clsx'
import api from '@/hooks/useApi'
import { useProjectStore } from '@/stores/useProjectStore'

// ── Types ──────────────────────────────────────────────────────────────────────

interface DuplicateImage {
  id: string
  filepath: string
  thumbnail_url: string
  score: number // similarity score to cluster center
  quality_score?: number
  keep: boolean
}

interface DuplicateCluster {
  id: string
  cluster_type: 'exact' | 'near' | 'similar'
  image_count: number
  images: DuplicateImage[]
  best_id: string // recommended keep
}

interface DuplicatesResponse {
  clusters: DuplicateCluster[]
  total_clusters: number
  total_duplicates: number
}

type ClusterTypeFilter = 'all' | 'exact' | 'near' | 'similar'

const CLUSTER_TYPE_LABELS: Record<string, string> = {
  exact: 'Exact',
  near: 'Near-duplicate',
  similar: 'Similar',
}

const CLUSTER_TYPE_COLORS: Record<string, string> = {
  exact: 'text-red-400 bg-red-400/10',
  near: 'text-orange-400 bg-orange-400/10',
  similar: 'text-yellow-400 bg-yellow-400/10',
}

// ── Cluster card ───────────────────────────────────────────────────────────────

interface ClusterCardProps {
  cluster: DuplicateCluster
  isSelected: boolean
  onClick: () => void
}

function ClusterCard({ cluster, isSelected, onClick }: ClusterCardProps) {
  const keepCount = cluster.images.filter((i) => i.keep).length
  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full text-left px-3 py-2.5 rounded-md border transition-colors',
        isSelected
          ? 'bg-accent/20 border-accent'
          : 'bg-surface border-border hover:bg-surface-elevated'
      )}
    >
      <div className="flex items-center justify-between mb-1">
        <span
          className={clsx(
            'text-xs font-medium px-1.5 py-0.5 rounded',
            CLUSTER_TYPE_COLORS[cluster.cluster_type] ?? 'text-text-secondary bg-surface-elevated'
          )}
        >
          {CLUSTER_TYPE_LABELS[cluster.cluster_type] ?? cluster.cluster_type}
        </span>
        <span className="text-xs text-text-secondary">{cluster.image_count} images</span>
      </div>
      <div className="text-xs text-text-secondary">
        Keep {keepCount} / {cluster.image_count}
      </div>
    </button>
  )
}

// ── Image tile ─────────────────────────────────────────────────────────────────

interface ImageTileProps {
  image: DuplicateImage
  isBest: boolean
  onToggle: (id: string) => void
}

function ImageTile({ image, isBest, onToggle }: ImageTileProps) {
  return (
    <div
      className={clsx(
        'relative rounded-lg border overflow-hidden cursor-pointer group',
        image.keep ? 'border-green-500' : 'border-border opacity-60'
      )}
      onClick={() => onToggle(image.id)}
    >
      <img
        src={image.thumbnail_url}
        alt=""
        className="w-full aspect-square object-cover"
        loading="lazy"
      />

      {/* Keep/remove overlay */}
      <div
        className={clsx(
          'absolute inset-0 flex items-center justify-center',
          'transition-opacity',
          image.keep ? 'opacity-0 group-hover:opacity-100' : 'opacity-100'
        )}
        style={{ background: image.keep ? 'rgba(0,0,0,0.3)' : 'rgba(0,0,0,0.55)' }}
      >
        {image.keep ? (
          <Trash2 size={20} className="text-white" />
        ) : (
          <CheckCircle size={20} className="text-white" />
        )}
      </div>

      {/* Best badge */}
      {isBest && (
        <div className="absolute top-1 left-1 bg-green-500 text-white text-xs px-1.5 py-0.5 rounded font-medium">
          Best
        </div>
      )}

      {/* Score */}
      {image.quality_score !== undefined && (
        <div className="absolute bottom-1 right-1 bg-black/60 text-white text-xs px-1.5 py-0.5 rounded">
          {Math.round(image.quality_score * 100)}
        </div>
      )}

      {/* Keep indicator */}
      {image.keep && (
        <CheckCircle
          size={14}
          className="absolute top-1 right-1 text-green-400"
        />
      )}
    </div>
  )
}

// ── Main view ──────────────────────────────────────────────────────────────────

export function Duplicates() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const queryClient = useQueryClient()

  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState<ClusterTypeFilter>('all')
  const [localKeep, setLocalKeep] = useState<Record<string, Record<string, boolean>>>({})

  const { data, isLoading, error } = useQuery<DuplicatesResponse>({
    queryKey: ['duplicates', activeProject?.id],
    queryFn: () =>
      api
        .get<DuplicatesResponse>(`/api/projects/${activeProject!.id}/duplicates`)
        .then((r) => r.data),
    enabled: !!activeProject,
  })

  const removeMutation = useMutation({
    mutationFn: (imageIds: string[]) =>
      api.post(`/api/assets/bulk-delete`, { ids: imageIds }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['duplicates', activeProject?.id] })
      queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
  })

  const filteredClusters = (data?.clusters ?? []).filter(
    (c) => typeFilter === 'all' || c.cluster_type === typeFilter
  )

  const selectedCluster = filteredClusters.find((c) => c.id === selectedClusterId) ?? null

  // Merge server keep state with local overrides
  const getEffectiveImages = useCallback(
    (cluster: DuplicateCluster): DuplicateImage[] => {
      const overrides = localKeep[cluster.id] ?? {}
      return cluster.images.map((img) => ({
        ...img,
        keep: img.id in overrides ? overrides[img.id] : img.keep,
      }))
    },
    [localKeep]
  )

  const handleToggle = (clusterId: string, imageId: string) => {
    setLocalKeep((prev) => {
      const clusterOverrides = { ...(prev[clusterId] ?? {}) }
      const cluster = data?.clusters.find((c) => c.id === clusterId)
      if (!cluster) return prev
      const currentKeep =
        imageId in clusterOverrides
          ? clusterOverrides[imageId]
          : (cluster.images.find((i) => i.id === imageId)?.keep ?? true)
      clusterOverrides[imageId] = !currentKeep
      return { ...prev, [clusterId]: clusterOverrides }
    })
  }

  const handleKeepBest = (cluster: DuplicateCluster) => {
    const overrides: Record<string, boolean> = {}
    cluster.images.forEach((img) => {
      overrides[img.id] = img.id === cluster.best_id
    })
    setLocalKeep((prev) => ({ ...prev, [cluster.id]: overrides }))
  }

  const handleApplyCluster = (cluster: DuplicateCluster) => {
    const images = getEffectiveImages(cluster)
    const toRemove = images.filter((i) => !i.keep).map((i) => i.id)
    if (toRemove.length > 0) {
      removeMutation.mutate(toRemove)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (!activeProject) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-text-secondary gap-2">
        <Layers size={32} className="opacity-40" />
        <p>Select a project to view duplicates</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full gap-2 text-text-secondary">
        <Loader2 size={20} className="animate-spin" />
        <span>Scanning for duplicates…</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full gap-2 text-red-400">
        <AlertCircle size={20} />
        <span>Failed to load duplicates</span>
      </div>
    )
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Sidebar: cluster list ── */}
      <div className="w-64 flex-shrink-0 flex flex-col border-r border-border bg-surface">
        {/* Header */}
        <div className="px-3 py-3 border-b border-border">
          <div className="flex items-center gap-2 mb-2">
            <Layers size={16} className="text-accent" />
            <span className="font-semibold text-sm">Duplicate Clusters</span>
          </div>
          <div className="text-xs text-text-secondary">
            {data?.total_clusters ?? 0} clusters · {data?.total_duplicates ?? 0} duplicates
          </div>
        </div>

        {/* Type filter */}
        <div className="px-3 py-2 border-b border-border flex gap-1 flex-wrap">
          {(['all', 'exact', 'near', 'similar'] as ClusterTypeFilter[]).map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={clsx(
                'text-xs px-2 py-0.5 rounded capitalize',
                typeFilter === t
                  ? 'bg-accent text-white'
                  : 'bg-surface-elevated text-text-secondary hover:text-text-primary'
              )}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Cluster list */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
          {filteredClusters.length === 0 ? (
            <p className="text-xs text-text-secondary text-center py-4">No clusters found</p>
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

      {/* ── Main: cluster detail ── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {!selectedCluster ? (
          <div className="flex items-center justify-center h-full text-text-secondary gap-2">
            <Layers size={24} className="opacity-40" />
            <span>Select a cluster to review</span>
          </div>
        ) : (
          <>
            {/* Cluster toolbar */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-border bg-surface flex-shrink-0">
              <span
                className={clsx(
                  'text-xs font-medium px-2 py-0.5 rounded',
                  CLUSTER_TYPE_COLORS[selectedCluster.cluster_type] ?? ''
                )}
              >
                {CLUSTER_TYPE_LABELS[selectedCluster.cluster_type]}
              </span>
              <span className="text-sm text-text-secondary">
                {selectedCluster.image_count} images
              </span>

              <div className="ml-auto flex gap-2">
                <button
                  onClick={() => handleKeepBest(selectedCluster)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface-elevated border border-border rounded-md hover:bg-accent/10 hover:border-accent transition-colors"
                >
                  <CheckCircle size={13} />
                  Keep Best
                </button>
                <button
                  onClick={() => handleApplyCluster(selectedCluster)}
                  disabled={removeMutation.isPending}
                  className={clsx(
                    'flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md transition-colors',
                    'bg-red-500/10 border border-red-500/30 text-red-400',
                    'hover:bg-red-500/20 disabled:opacity-50 disabled:cursor-not-allowed'
                  )}
                >
                  {removeMutation.isPending ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Trash2 size={13} />
                  )}
                  Remove Marked
                </button>
              </div>
            </div>

            {/* Image grid */}
            <div className="flex-1 overflow-y-auto p-4">
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-2">
                {getEffectiveImages(selectedCluster).map((img) => (
                  <ImageTile
                    key={img.id}
                    image={img}
                    isBest={img.id === selectedCluster.best_id}
                    onToggle={(id) => handleToggle(selectedCluster.id, id)}
                  />
                ))}
              </div>

              {/* Legend */}
              <div className="mt-4 flex gap-4 text-xs text-text-secondary">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded border border-green-500 inline-block" />
                  Keep
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded border border-border opacity-60 inline-block" />
                  Remove
                </span>
                <span className="ml-2 text-text-secondary/70">Click image to toggle · Best = highest quality score</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default Duplicates
