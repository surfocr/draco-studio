import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  X,
  Check,
  Flag,
  RotateCw,
  Brain,
  Sparkles,
  User,
  Camera,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { clsx } from 'clsx'
import { assetsApi, captionsApi } from '@/hooks/useApi'
import { Score } from './Score'
import type { CaptionVersion } from '@/types/api'

interface AssetDetailPanelProps {
  assetId: string
  onClose: () => void
  onApprove: (id: string) => void
  onReject: (id: string) => void
  onFlag: (id: string) => void
  onPrev?: () => void
  onNext?: () => void
  hasPrev?: boolean
  hasNext?: boolean
}

function ScoreBar({ label, value, icon: Icon }: { label: string; value: number | null; icon?: React.ElementType }) {
  if (value == null) return null
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? '#22c55e' : pct >= 60 ? '#84cc16' : pct >= 40 ? '#f59e0b' : '#ef4444'

  return (
    <div className="flex items-center gap-2">
      {Icon && <Icon size={13} className="flex-shrink-0 text-text-secondary" />}
      <span className="w-24 text-xs text-text-secondary truncate">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-surface-elevated overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="w-8 text-right text-xs font-mono" style={{ color }}>{pct}</span>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (value == null || value === '') return null
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="w-24 flex-shrink-0 text-text-secondary">{label}</span>
      <span className="text-text-primary break-all">{value}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">{title}</h4>
      {children}
    </div>
  )
}

export function AssetDetailPanel({
  assetId,
  onClose,
  onApprove,
  onReject,
  onFlag,
  onPrev,
  onNext,
  hasPrev = false,
  hasNext = false,
}: AssetDetailPanelProps) {
  const { data: asset, isLoading } = useQuery({
    queryKey: ['asset-detail', assetId],
    queryFn: () => assetsApi.get(assetId),
    enabled: !!assetId,
  })

  const { data: captions } = useQuery({
    queryKey: ['asset-captions', assetId],
    queryFn: () => captionsApi.list(assetId),
    enabled: !!assetId,
  })

  // Keyboard nav
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft' && hasPrev && onPrev) onPrev()
      if (e.key === 'ArrowRight' && hasNext && onNext) onNext()
      if (e.key === 'a' && !e.ctrlKey && !e.metaKey && asset) onApprove(asset.id)
      if (e.key === 'r' && !e.ctrlKey && !e.metaKey && asset) onReject(asset.id)
      if (e.key === 'f' && !e.ctrlKey && !e.metaKey && asset) onFlag(asset.id)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose, onPrev, onNext, hasPrev, hasNext, asset, onApprove, onReject, onFlag])

  const activeCaption = captions?.find((c: CaptionVersion) => c.is_active)

  const formatBytes = (bytes: number | null) => {
    if (bytes == null) return null
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const formatPose = (yaw: number | null, pitch: number | null, roll: number | null) => {
    if (yaw == null && pitch == null && roll == null) return null
    const parts = []
    if (yaw != null) parts.push(`Y:${Math.round(yaw)}°`)
    if (pitch != null) parts.push(`P:${Math.round(pitch)}°`)
    if (roll != null) parts.push(`R:${Math.round(roll)}°`)
    return parts.join(' ')
  }

  return (
    <div className="flex flex-col h-full border-l border-border bg-surface" style={{ width: 360 }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-1">
          <button
            className="btn-ghost btn-icon"
            onClick={onPrev}
            disabled={!hasPrev}
            title="Previous (←)"
          >
            <ChevronLeft size={14} />
          </button>
          <button
            className="btn-ghost btn-icon"
            onClick={onNext}
            disabled={!hasNext}
            title="Next (→)"
          >
            <ChevronRight size={14} />
          </button>
        </div>
        <span className="flex-1 text-sm font-medium text-text-primary truncate">
          {asset?.filename ?? 'Loading...'}
        </span>
        <button className="btn-ghost btn-icon" onClick={onClose} title="Close (Esc)">
          <X size={14} />
        </button>
      </div>

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center text-text-secondary">
          <RotateCw size={20} className="animate-spin" />
        </div>
      ) : asset ? (
        <div className="flex-1 overflow-y-auto">
          {/* Image preview */}
          <div className="relative bg-black">
            <img
              src={assetsApi.originalUrl(asset.id)}
              alt={asset.filename}
              className="w-full object-contain"
              style={{ maxHeight: 280 }}
            />
            {/* Review state badge */}
            <div className="absolute top-2 right-2">
              <span
                className={clsx('badge text-[10px]', {
                  'badge-green': asset.review_state === 'approved',
                  'badge-red': asset.is_rejected,
                  'badge-yellow': asset.is_flagged && !asset.is_rejected,
                })}
                style={
                  asset.review_state === 'approved'
                    ? { background: 'rgba(34,197,94,0.2)', color: '#22c55e' }
                    : asset.is_rejected
                    ? { background: 'rgba(239,68,68,0.2)', color: '#ef4444' }
                    : asset.is_flagged
                    ? { background: 'rgba(245,158,11,0.2)', color: '#f59e0b' }
                    : { background: 'rgba(148,163,184,0.2)', color: '#94a3b8' }
                }
              >
                {asset.is_rejected ? 'Rejected' : asset.is_flagged ? 'Flagged' : asset.review_state === 'approved' ? 'Approved' : 'Pending'}
              </span>
            </div>
          </div>

          {/* Quick actions */}
          <div className="flex gap-2 px-3 py-2 border-b border-border">
            <button
              className={clsx('btn btn-sm flex-1', asset.review_state === 'approved' && 'ring-1 ring-green-500')}
              style={{ background: 'rgba(34,197,94,0.15)', color: 'var(--success)', border: '1px solid rgba(34,197,94,0.3)' }}
              onClick={() => onApprove(asset.id)}
            >
              <Check size={12} /> Approve
            </button>
            <button
              className="btn btn-sm flex-1"
              style={{ background: 'rgba(245,158,11,0.15)', color: 'var(--warning)', border: '1px solid rgba(245,158,11,0.3)' }}
              onClick={() => onFlag(asset.id)}
            >
              <Flag size={12} /> Flag
            </button>
            <button
              className="btn btn-danger btn-sm flex-1"
              onClick={() => onReject(asset.id)}
            >
              <X size={12} /> Reject
            </button>
          </div>

          {/* Content sections */}
          <div className="space-y-4 px-3 py-3">
            {/* Composite Score */}
            <div className="flex items-center gap-3">
              <span className="text-xs text-text-secondary">Overall</span>
              <Score value={asset.composite_score} size="lg" showLabel />
              {asset.training_usefulness != null && (
                <>
                  <span className="text-xs text-text-secondary ml-auto">Training Value</span>
                  <Score value={asset.training_usefulness} size="lg" showLabel />
                </>
              )}
            </div>

            {/* Quality Scores */}
            <Section title="Quality Scores">
              <div className="space-y-1.5">
                <ScoreBar label="Technical" value={asset.technical_quality} icon={Camera} />
                <ScoreBar label="Aesthetic" value={asset.aesthetic_score} icon={Sparkles} />
                <ScoreBar label="Face Quality" value={asset.face_quality} icon={User} />
                <ScoreBar label="Training" value={asset.training_usefulness} icon={Brain} />
              </div>
              {asset.score_breakdown && Object.keys(asset.score_breakdown).length > 0 && (
                <details className="mt-2">
                  <summary className="text-[10px] text-text-secondary cursor-pointer hover:text-text-primary">
                    Full breakdown
                  </summary>
                  <div className="mt-1 space-y-1">
                    {Object.entries(asset.score_breakdown).map(([key, val]) => (
                      <ScoreBar key={key} label={key.replace(/_/g, ' ')} value={val} />
                    ))}
                  </div>
                </details>
              )}
            </Section>

            {/* Face Analysis */}
            {asset.face_count > 0 && (
              <Section title="Face Analysis">
                <div className="space-y-1">
                  <InfoRow label="Faces" value={asset.face_count} />
                  <InfoRow label="Head Pose" value={formatPose(asset.head_pose_yaw, asset.head_pose_pitch, asset.head_pose_roll)} />
                  <InfoRow label="Age" value={asset.age_estimate != null ? `~${Math.round(asset.age_estimate)}` : null} />
                  <InfoRow label="Gender" value={asset.gender_estimate} />
                  <InfoRow label="Emotion" value={asset.dominant_emotion} />
                  <InfoRow label="Gaze" value={asset.gaze_direction} />
                </div>
              </Section>
            )}

            {/* Scene */}
            {(asset.scene_class || asset.scene_tags?.length) && (
              <Section title="Scene">
                <div className="space-y-1">
                  <InfoRow label="Indoor" value={asset.is_indoor != null ? (asset.is_indoor ? 'Yes' : 'No') : null} />
                  <InfoRow label="Scene" value={asset.scene_class} />
                  {asset.scene_tags && asset.scene_tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {asset.scene_tags.map((tag) => (
                        <span key={tag} className="badge text-[10px]">{tag}</span>
                      ))}
                    </div>
                  )}
                </div>
              </Section>
            )}

            {/* Caption */}
            <Section title="Caption">
              {activeCaption ? (
                <div className="space-y-1">
                  <p className="text-xs text-text-primary leading-relaxed whitespace-pre-wrap bg-surface-elevated rounded-md p-2">
                    {activeCaption.text}
                  </p>
                  <div className="flex items-center gap-2 text-[10px] text-text-secondary">
                    <span>{activeCaption.provider}</span>
                    {activeCaption.model && <span>• {activeCaption.model}</span>}
                    <span>• {activeCaption.style}</span>
                    {activeCaption.is_edited && <span className="text-accent">• edited</span>}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-text-secondary italic">No caption generated</p>
              )}
              {captions && captions.length > 1 && (
                <details className="mt-1">
                  <summary className="text-[10px] text-text-secondary cursor-pointer hover:text-text-primary">
                    {captions.length - 1} other version{captions.length > 2 ? 's' : ''}
                  </summary>
                  <div className="mt-1 space-y-1">
                    {captions
                      .filter((c: CaptionVersion) => !c.is_active)
                      .map((c: CaptionVersion) => (
                        <div key={c.id} className="text-[10px] text-text-secondary bg-surface-elevated rounded p-1.5">
                          <span className="font-medium">{c.provider}/{c.style}</span>: {c.text.slice(0, 120)}
                          {c.text.length > 120 && '...'}
                        </div>
                      ))}
                  </div>
                </details>
              )}
            </Section>

            {/* Ranking */}
            {asset.ranking_comparisons_count > 0 && (
              <Section title="Ranking">
                <div className="space-y-1">
                  <InfoRow label="TrueSkill μ" value={asset.trueskill_mu.toFixed(1)} />
                  <InfoRow label="TrueSkill σ" value={asset.trueskill_sigma.toFixed(2)} />
                  <InfoRow label="Elo" value={Math.round(asset.elo_rating)} />
                  <InfoRow label="Comparisons" value={asset.ranking_comparisons_count} />
                </div>
              </Section>
            )}

            {/* File Info */}
            <Section title="File Info">
              <div className="space-y-1">
                <InfoRow label="Filename" value={asset.filename} />
                {asset.width && asset.height && (
                  <InfoRow label="Dimensions" value={`${asset.width} × ${asset.height}`} />
                )}
                <InfoRow label="Size" value={formatBytes(asset.file_size)} />
                <InfoRow label="Format" value={asset.mime_type} />
                <InfoRow label="Shot Type" value={asset.shot_type !== 'unknown' ? asset.shot_type?.replace(/_/g, ' ') : null} />
                <InfoRow label="Imported" value={asset.imported_at ? new Date(asset.imported_at).toLocaleString() : null} />
                <InfoRow label="Analyzed" value={asset.analyzed_at ? new Date(asset.analyzed_at).toLocaleString() : null} />
                {asset.sha256_hash && (
                  <InfoRow label="SHA-256" value={
                    <span className="font-mono text-[10px]" title={asset.sha256_hash}>
                      {asset.sha256_hash.slice(0, 16)}...
                    </span>
                  } />
                )}
              </div>
            </Section>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center text-text-secondary text-sm">
          Asset not found
        </div>
      )}
    </div>
  )
}
