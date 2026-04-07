import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Users, Edit2, Merge, RefreshCw, X, ShieldCheck, AlertTriangle } from 'lucide-react'
import { useProjectStore } from '@/stores/useProjectStore'
import { useJobStore } from '@/stores/useJobStore'
import { facesApi } from '@/hooks/useApi'
import { useToast } from '@/components/providers/ToastProvider'

interface FaceCluster {
  id: string
  label: string | null
  face_count: number
  asset_ids: string[]
  thumbnail_url: string | null
  identity_consistency_score: number | null
}

interface Asset {
  id: string
  filename: string
  thumbnail_url: string
  composite_score: number
  face_quality: number | null
  face_sharpness: number | null
  head_pose_yaw: number | null
  age_estimate: number | null
  gender_estimate: string | null
  face_count: number
}

/** Format 0-1 score as a coloured percentage badge. */
function ScoreBadge({ value, label }: { value: number | null; label: string }) {
  if (value == null) return null
  const pct = Math.round(value * 100)
  const colour =
    pct >= 70 ? 'text-emerald-400' : pct >= 40 ? 'text-amber-400' : 'text-red-400'
  return (
    <span className={`text-xs font-mono ${colour}`} title={label}>
      {label} {pct}%
    </span>
  )
}

/** Pose acceptability badge based on yaw angle. */
function PoseBadge({ yaw }: { yaw: number | null }) {
  if (yaw == null) return null
  const abs = Math.abs(yaw)
  const label = abs <= 20 ? 'Front' : abs <= 45 ? 'Side' : 'Profile'
  const colour =
    abs <= 20 ? 'text-emerald-400' : abs <= 45 ? 'text-amber-400' : 'text-red-400'
  return (
    <span className={`text-xs ${colour}`} title={`Yaw ${yaw.toFixed(1)}°`}>
      {label}
    </span>
  )
}

/** Consistency badge for an identity cluster. */
function ConsistencyBadge({ score }: { score: number | null }) {
  if (score == null) return null
  const pct = Math.round(score * 100)
  const Icon = pct >= 70 ? ShieldCheck : AlertTriangle
  const colour = pct >= 70 ? 'text-emerald-400' : pct >= 50 ? 'text-amber-400' : 'text-red-400'
  return (
    <span
      className={`flex items-center gap-0.5 text-xs font-mono ${colour}`}
      title={`Identity consistency ${pct}%`}
    >
      <Icon size={11} />
      {pct}%
    </span>
  )
}

export function Faces() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const addJob = useJobStore((s) => s.addJob)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [selectedCluster, setSelectedCluster] = useState<FaceCluster | null>(null)
  const [mergeMode, setMergeMode] = useState(false)
  const [mergeTarget, setMergeTarget] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [minFaces, setMinFaces] = useState(1)
  const [minFaceQuality, setMinFaceQuality] = useState(0)
  const [maxYaw, setMaxYaw] = useState(90)

  const { data: clusters = [], isLoading } = useQuery({
    queryKey: ['face-clusters', activeProject?.id],
    queryFn: () => facesApi.listClusters(activeProject!.id),
    enabled: !!activeProject,
  })

  const { data: clusterAssets = [] } = useQuery<Asset[]>({
    queryKey: ['cluster-assets', selectedCluster?.id],
    queryFn: () => facesApi.getClusterAssets(selectedCluster!.id),
    enabled: !!selectedCluster,
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) =>
      facesApi.renameCluster(id, label),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['face-clusters'] })
      setRenamingId(null)
    },
  })

  const mergeMutation = useMutation({
    mutationFn: ({ source_id, target_id }: { source_id: string; target_id: string }) =>
      facesApi.mergeClusters(source_id, target_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['face-clusters'] })
      setMergeMode(false)
      setMergeTarget(null)
      setSelectedCluster(null)
    },
  })

  const clusterMutation = useMutation({
    mutationFn: () => facesApi.runClustering(activeProject!.id),
    onSuccess: (result) => {
      addJob({
        id: result.job_id,
        type: 'face_clustering',
        status: 'pending',
        progress: 0,
        message: 'Clustering identities',
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
      })
      toast.success('Identity clustering started')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to start identity clustering')
    },
  })

  const filtered = clusters.filter((c: FaceCluster) => c.face_count >= minFaces)

  if (!activeProject) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500">
        No project selected
      </div>
    )
  }

  return (
    <div className="flex h-full bg-zinc-950">
      {/* Cluster Grid */}
      <div className="flex-1 flex flex-col">
        <div className="p-4 border-b border-zinc-800 flex items-center gap-4">
          <h1 className="text-lg font-semibold text-white flex items-center gap-2">
            <Users size={20} className="text-violet-400" />
            Identity Clusters
          </h1>
          <span className="text-zinc-400 text-sm">{filtered.length} identities</span>
          <div className="ml-auto flex items-center gap-3">
            <button
              onClick={() => clusterMutation.mutate()}
              disabled={clusterMutation.isPending}
              className="btn btn-secondary btn-sm flex items-center gap-1.5"
            >
              {clusterMutation.isPending ? (
                <RefreshCw size={12} className="animate-spin" />
              ) : (
                <Users size={12} />
              )}
              Run Clustering
            </button>
            <label className="text-zinc-400 text-sm">Min faces:</label>
            <input
              type="number"
              min={1}
              value={minFaces}
              onChange={e => setMinFaces(+e.target.value)}
              className="w-16 bg-zinc-800 text-white text-sm rounded px-2 py-1 border border-zinc-700"
            />
            <label className="text-zinc-400 text-sm">Min FQ:</label>
            <input
              type="number"
              min={0}
              max={100}
              step={5}
              value={minFaceQuality}
              onChange={e => setMinFaceQuality(+e.target.value)}
              className="w-16 bg-zinc-800 text-white text-sm rounded px-2 py-1 border border-zinc-700"
              title="Minimum face quality % for assets shown in cluster panel"
            />
            <label className="text-zinc-400 text-sm">Max yaw:</label>
            <input
              type="number"
              min={0}
              max={90}
              step={5}
              value={maxYaw}
              onChange={e => setMaxYaw(+e.target.value)}
              className="w-16 bg-zinc-800 text-white text-sm rounded px-2 py-1 border border-zinc-700"
              title="Maximum absolute head yaw angle (degrees) — 90 = all poses"
            />
            <button
              onClick={() => { setMergeMode(!mergeMode); setMergeTarget(null) }}
              className={`px-3 py-1.5 rounded text-sm font-medium flex items-center gap-1.5 ${
                mergeMode
                  ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                  : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              <Merge size={14} />
              {mergeMode ? 'Cancel Merge' : 'Merge Mode'}
            </button>
          </div>
        </div>

        {mergeMode && mergeTarget !== null && (
          <div className="px-4 py-2 bg-amber-500/10 border-b border-amber-500/20 text-amber-400 text-sm">
            Select second cluster to merge into cluster #{mergeTarget}
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center h-64 text-zinc-500">Loading clusters...</div>
        ) : (
          <div className="p-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 overflow-y-auto">
            {filtered.map((cluster: FaceCluster) => (
              <div
                key={cluster.id}
                onClick={() => {
                  if (mergeMode) {
                    if (mergeTarget === null) {
                      setMergeTarget(cluster.id)
                    } else if (mergeTarget !== cluster.id) {
                      mergeMutation.mutate({ source_id: cluster.id, target_id: mergeTarget })
                    }
                  } else {
                    setSelectedCluster(cluster)
                  }
                }}
                className={`relative rounded-lg border cursor-pointer transition-all ${
                  selectedCluster?.id === cluster.id
                    ? 'border-violet-500 bg-violet-500/10'
                    : mergeTarget === cluster.id
                    ? 'border-amber-500 bg-amber-500/10'
                    : 'border-zinc-800 bg-zinc-900 hover:border-zinc-600'
                }`}
              >
                <div className="aspect-square rounded-t-lg overflow-hidden bg-zinc-800">
                  {cluster.thumbnail_url ? (
                    <img src={cluster.thumbnail_url} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-zinc-600">
                      <Users size={32} />
                    </div>
                  )}
                </div>
                <div className="p-2">
                  {renamingId === cluster.id ? (
                    <div className="flex gap-1" onClick={e => e.stopPropagation()}>
                      <input
                        autoFocus
                        value={renameValue}
                        onChange={e => setRenameValue(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter') renameMutation.mutate({ id: cluster.id, label: renameValue })
                          if (e.key === 'Escape') setRenamingId(null)
                        }}
                        className="flex-1 min-w-0 bg-zinc-700 text-white text-xs rounded px-1.5 py-1 border border-zinc-600"
                      />
                      <button
                        onClick={() => renameMutation.mutate({ id: cluster.id, label: renameValue })}
                        className="text-violet-400 hover:text-violet-300 text-xs px-1"
                      >✓</button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-white text-xs font-medium truncate">
                        {cluster.label || `Identity ${cluster.id.slice(0, 6)}`}
                      </span>
                      <button
                        onClick={e => {
                          e.stopPropagation()
                          setRenamingId(cluster.id)
                          setRenameValue(cluster.label || '')
                        }}
                        className="text-zinc-500 hover:text-zinc-300 flex-shrink-0"
                      >
                        <Edit2 size={11} />
                      </button>
                    </div>
                  )}
                  <div className="flex items-center justify-between mt-0.5">
                    <div className="text-zinc-500 text-xs">{cluster.face_count} faces</div>
                    <ConsistencyBadge score={cluster.identity_consistency_score} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Asset Panel */}
      {selectedCluster && (
        <div className="w-80 border-l border-zinc-800 flex flex-col bg-zinc-900">
          <div className="p-3 border-b border-zinc-800 flex items-center justify-between">
            <div>
              <div className="text-white text-sm font-medium">
                {selectedCluster.label || `Identity ${selectedCluster.id.slice(0, 6)}`}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-zinc-500 text-xs">{selectedCluster.face_count} images</span>
                <ConsistencyBadge score={selectedCluster.identity_consistency_score} />
              </div>
            </div>
            <button onClick={() => setSelectedCluster(null)} className="text-zinc-500 hover:text-zinc-300">
              <X size={16} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 grid grid-cols-2 gap-2">
            {clusterAssets
              .filter(
                (a) =>
                  (a.face_quality == null || a.face_quality * 100 >= minFaceQuality) &&
                  (a.head_pose_yaw == null || Math.abs(a.head_pose_yaw) <= maxYaw),
              )
              .map((asset: Asset) => (
              <div key={asset.id} className="relative rounded overflow-hidden bg-zinc-800 aspect-square">
                {asset.thumbnail_url ? (
                  <img src={asset.thumbnail_url} alt={asset.filename} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-zinc-600 text-xs">
                    {asset.filename}
                  </div>
                )}
                <div className="absolute bottom-0 left-0 right-0 bg-black/60 px-1.5 py-0.5 flex flex-col gap-0.5">
                  <div className="flex items-center justify-between">
                    <ScoreBadge value={asset.face_quality} label="FQ" />
                    <PoseBadge yaw={asset.head_pose_yaw} />
                  </div>
                  <div className="flex items-center justify-between">
                    <ScoreBadge value={asset.face_sharpness} label="Sh" />
                    {asset.age_estimate != null && (
                      <span className="text-zinc-400 text-xs">{Math.round(asset.age_estimate)}y</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default Faces
