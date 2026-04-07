import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, ChevronLeft, ChevronRight, BarChart2, FileText, Eye } from 'lucide-react'
import axios from 'axios'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:18082' })

interface Asset {
  id: number
  filename: string
  file_path?: string
  thumbnail_url?: string
  width?: number
  height?: number
  composite_score?: number
  caption_text?: string
  face_count?: number
  dominant_emotion?: string
  shot_type?: string
  review_state?: string
  technical_quality?: number
  aesthetic_score?: number
  face_quality?: number
  trueskill_mu?: number
  is_augmented?: boolean
}

interface Props {
  asset: Asset
  onClose: () => void
  onPrev?: () => void
  onNext?: () => void
  hasPrev?: boolean
  hasNext?: boolean
}

type Tab = 'info' | 'caption' | 'scores'

export function AssetDetailModal({ asset, onClose, onPrev, onNext, hasPrev, hasNext }: Props) {
  const [tab, setTab] = useState<Tab>('info')
  const [showScores, setShowScores] = useState(false)

  const { data: explainData } = useQuery({
    queryKey: ['explain', asset.id],
    queryFn: () => api.get(`/api/assets/${asset.id}/explain`).then(r => r.data),
    enabled: showScores,
  })

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft' && onPrev && hasPrev) onPrev()
      if (e.key === 'ArrowRight' && onNext && hasNext) onNext()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose, onPrev, onNext, hasPrev, hasNext])

  const score_pct = asset.composite_score != null ? Math.round(asset.composite_score * 100) : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={onClose}>
      <div
        className="relative flex bg-zinc-900 rounded-xl overflow-hidden shadow-2xl border border-zinc-700 max-w-5xl w-full mx-4"
        style={{ maxHeight: '90vh' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Main image area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Image */}
          <div className="flex-1 flex items-center justify-center bg-zinc-950 relative min-h-0" style={{ maxHeight: '65vh' }}>
            {asset.thumbnail_url ? (
              <img
                src={asset.thumbnail_url}
                alt={asset.filename}
                className="max-w-full max-h-full object-contain"
              />
            ) : (
              <div className="text-zinc-600 text-sm">No preview</div>
            )}

            {/* Nav arrows */}
            {hasPrev && (
              <button
                onClick={onPrev}
                className="absolute left-2 top-1/2 -translate-y-1/2 bg-black/60 hover:bg-black/80 text-white rounded-full p-2 transition-colors"
              >
                <ChevronLeft size={20} />
              </button>
            )}
            {hasNext && (
              <button
                onClick={onNext}
                className="absolute right-2 top-1/2 -translate-y-1/2 bg-black/60 hover:bg-black/80 text-white rounded-full p-2 transition-colors"
              >
                <ChevronRight size={20} />
              </button>
            )}

            {/* Score overlay */}
            {score_pct != null && (
              <div className={`absolute top-2 right-2 text-sm font-mono font-bold px-2 py-1 rounded-lg border ${
                asset.composite_score! > 0.7 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                : asset.composite_score! > 0.4 ? 'bg-amber-500/20 text-amber-400 border-amber-500/30'
                : 'bg-red-500/20 text-red-400 border-red-500/30'
              }`}>
                {score_pct}%
              </div>
            )}
          </div>

          {/* Tab bar */}
          <div className="border-t border-zinc-800 px-4 py-2 flex items-center gap-1">
            {([
              { id: 'info' as Tab, label: 'Info', icon: Eye },
              { id: 'caption' as Tab, label: 'Caption', icon: FileText },
              { id: 'scores' as Tab, label: 'AI Scores', icon: BarChart2 },
            ] as const).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => {
                  setTab(id)
                  if (id === 'scores') setShowScores(true)
                }}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium ${
                  tab === id ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <Icon size={12} />
                {label}
              </button>
            ))}
            <button onClick={onClose} className="ml-auto text-zinc-500 hover:text-zinc-300">
              <X size={16} />
            </button>
          </div>

          {/* Tab content */}
          <div className="px-4 pb-4 overflow-y-auto" style={{ maxHeight: '25vh' }}>
            {tab === 'info' && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <span className="text-zinc-500">Filename</span>
                <span className="text-zinc-300 truncate">{asset.filename}</span>
                <span className="text-zinc-500">Dimensions</span>
                <span className="text-zinc-300">{asset.width}×{asset.height}</span>
                <span className="text-zinc-500">Faces</span>
                <span className="text-zinc-300">{asset.face_count ?? 0}</span>
                <span className="text-zinc-500">Expression</span>
                <span className="text-zinc-300 capitalize">{asset.dominant_emotion || '—'}</span>
                <span className="text-zinc-500">Shot type</span>
                <span className="text-zinc-300 capitalize">{asset.shot_type || '—'}</span>
                <span className="text-zinc-500">Review</span>
                <span className={`capitalize ${
                  asset.review_state === 'approved' ? 'text-emerald-400'
                  : asset.review_state === 'rejected' ? 'text-red-400'
                  : 'text-zinc-400'
                }`}>{asset.review_state || 'pending'}</span>
                {asset.is_augmented && (
                  <>
                    <span className="text-zinc-500">Type</span>
                    <span className="text-violet-400">Augmented</span>
                  </>
                )}
              </div>
            )}
            {tab === 'caption' && (
              <div>
                {asset.caption_text ? (
                  <p className="text-zinc-300 text-xs leading-relaxed">{asset.caption_text}</p>
                ) : (
                  <p className="text-zinc-600 text-xs italic">No caption yet. Go to the Captions tab to generate one.</p>
                )}
              </div>
            )}
            {tab === 'scores' && (
              <div className="text-zinc-500 text-xs">
                {showScores && !explainData && <span className="text-zinc-600">Loading AI scores...</span>}
                {explainData && (
                  <div className="space-y-2">
                    {explainData.dimensions?.map((d: any) => (
                      <div key={d.key}>
                        <div className="flex justify-between mb-0.5">
                          <span className="text-zinc-300">{d.label}</span>
                          <span className={d.score > 0.7 ? 'text-emerald-400' : d.score > 0.4 ? 'text-amber-400' : 'text-red-400'}>
                            {Math.round(d.score * 100)}%
                          </span>
                        </div>
                        <div className="h-1 bg-zinc-800 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${d.score > 0.7 ? 'bg-emerald-500' : d.score > 0.4 ? 'bg-amber-500' : 'bg-red-500'}`} style={{ width: `${d.score * 100}%` }} />
                        </div>
                        {d.rationale && <p className="text-zinc-600 text-[10px] mt-0.5">{d.rationale}</p>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
