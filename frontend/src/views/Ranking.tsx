import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Trophy,
  RefreshCw,
  SkipForward,
  Bot,
  ChevronDown,
  ChevronUp,
  Plus,
  Download,
  CheckCircle,
  Layers,
  Star,
  X,
  AlertTriangle,
  ArrowUpDown,
  RotateCcw,
} from 'lucide-react'
import { clsx } from 'clsx'
import { rankingApi, assetsApi } from '@/hooks/useApi'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useProjectStore } from '@/stores/useProjectStore'
import { useAssetStore } from '@/stores/useAssetStore'
import { useToast } from '@/components/providers/ToastProvider'
import { Score } from '@/components/ui/Score'
import type {
  RankingSession,
  RankingAssetPair,
  LeaderboardEntry,
  AIJudgeResult,
  AIJudgeComparisonResult,
} from '@/types/api'

// ── Types ──────────────────────────────────────────────────────────────────────

type ActiveTab = 'arena' | 'leaderboard' | 'ai-judge'
type RankingEngine = 'openskill' | 'elo'
type RankingScope = 'all' | 'selected'
type RankingStrategy = 'uncertainty' | 'random' | 'balanced'
type AIFilter = 'all' | 'needs_review' | 'keep' | 'maybe' | 'remove'
type AISort = 'composite' | 'training_value' | 'confidence'

interface SessionSetupForm {
  name: string
  engine: RankingEngine
  scope: RankingScope
  strategy: RankingStrategy
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function confidenceValue(sigma: number): number {
  return Math.max(0, Math.min(1, 1 - sigma / 8.333))
}

function scoreColorClass(_value: number, total: number, rank: number): string {
  if (rank <= Math.floor(total * 0.25)) return 'text-green-400'
  if (rank > Math.floor(total * 0.75)) return 'text-red-400'
  return 'text-text-primary'
}

function recommendationBadge(rec: AIJudgeResult['recommendation']) {
  if (rec === 'keep')
    return (
      <span className="badge text-[10px] px-1.5 py-0.5 rounded font-semibold bg-green-900/60 text-green-300 border border-green-700/50">
        Keep
      </span>
    )
  if (rec === 'maybe')
    return (
      <span className="badge text-[10px] px-1.5 py-0.5 rounded font-semibold bg-yellow-900/60 text-yellow-300 border border-yellow-700/50">
        Maybe
      </span>
    )
  return (
    <span className="badge text-[10px] px-1.5 py-0.5 rounded font-semibold bg-red-900/60 text-red-300 border border-red-700/50">
      Remove
    </span>
  )
}

function compositeScoreColor(value: number): string {
  if (value >= 0.8) return '#22c55e'
  if (value >= 0.6) return '#84cc16'
  if (value >= 0.4) return '#f59e0b'
  return '#ef4444'
}

// ── Sub-components ─────────────────────────────────────────────────────────────

interface ConfidenceBarProps {
  sigma: number
  className?: string
}
function ConfidenceBar({ sigma, className }: ConfidenceBarProps) {
  const conf = confidenceValue(sigma)
  const pct = Math.round(conf * 100)
  const color = conf >= 0.7 ? '#22c55e' : conf >= 0.45 ? '#f59e0b' : '#ef4444'
  return (
    <div className={clsx('flex items-center gap-1.5', className)}>
      <div className="flex-1 h-1.5 bg-surface-elevated rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="text-[10px] text-text-secondary tabular-nums w-7 text-right">{pct}%</span>
    </div>
  )
}

interface ArenaCardProps {
  asset: RankingAssetPair['asset_a']
  label: 'A' | 'B'
  keyHint: string
  onPick: () => void
  disabled: boolean
  flash: 'winner' | 'loser' | null
}
function ArenaCard({ asset, label, keyHint, onPick, disabled, flash }: ArenaCardProps) {
  return (
    <button
      onClick={onPick}
      disabled={disabled}
      className={clsx(
        'flex-1 flex flex-col card overflow-hidden group transition-all duration-200 text-left',
        'hover:border-accent/60 disabled:opacity-50 disabled:cursor-not-allowed',
        flash === 'winner' && 'ring-2 ring-green-400 border-green-400/60 animate-flash-win',
        flash === 'loser' && 'ring-2 ring-red-400/40 border-red-400/20 opacity-60'
      )}
    >
      {/* Image */}
      <div className="relative overflow-hidden" style={{ aspectRatio: '4/3' }}>
        <img
          src={assetsApi.thumbnailUrl(asset.id, 512)}
          alt={asset.filename}
          className="w-full h-full object-cover group-hover:scale-[1.02] transition-transform duration-200"
          draggable={false}
        />
        {/* Label badge */}
        <div className="absolute top-2 left-2">
          <span className="text-sm font-bold bg-black/75 text-white rounded px-2 py-0.5 tracking-wide">
            {label}
          </span>
        </div>
        {/* Composite score */}
        {asset.composite_score != null && (
          <div className="absolute top-2 right-2">
            <Score value={asset.composite_score} size="sm" />
          </div>
        )}
        {/* Hover overlay */}
        <div className="absolute inset-0 bg-accent/15 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
          <div className="bg-accent text-white font-semibold px-5 py-2 rounded-lg text-sm shadow-lg">
            {label} Wins
          </div>
        </div>
        {/* Flash overlay */}
        {flash === 'winner' && (
          <div className="absolute inset-0 bg-green-400/20 pointer-events-none" />
        )}
      </div>
      {/* Stats */}
      <div className="p-3 space-y-1.5">
        <p className="text-xs text-text-secondary truncate">{asset.filename}</p>
        <div className="flex items-center gap-3 text-[11px] text-text-secondary">
          <span>
            μ <span className="text-text-primary font-medium">{asset.trueskill_mu.toFixed(1)}</span>
          </span>
          <span>
            σ <span className="text-text-primary">{asset.trueskill_sigma.toFixed(1)}</span>
          </span>
          <span>
            #{' '}
            <span className="text-text-primary">{asset.ranking_comparisons_count}</span> comp
          </span>
        </div>
        <ConfidenceBar sigma={asset.trueskill_sigma} />
        <div className="text-[10px] text-text-secondary pt-0.5">
          Press{' '}
          <kbd className="px-1 py-0.5 rounded border border-border bg-surface-elevated text-text-primary font-mono text-[10px]">
            {keyHint}
          </kbd>{' '}
          to pick
        </div>
      </div>
    </button>
  )
}

// ── Session Setup Modal ────────────────────────────────────────────────────────

interface SessionSetupModalProps {
  onClose: () => void
  onCreated: (session: RankingSession) => void
  projectId: string
  selectedAssetIds: string[]
}
function SessionSetupModal({ onClose, onCreated, projectId, selectedAssetIds }: SessionSetupModalProps) {
  const toast = useToast()
  const [form, setForm] = useState<SessionSetupForm>({
    name: `Session ${new Date().toLocaleDateString()}`,
    engine: 'openskill',
    scope: 'all',
    strategy: 'uncertainty',
  })

  const createMutation = useMutation({
    mutationFn: () =>
      rankingApi.createSession(projectId, {
        name: form.name,
        engine: form.engine,
        scope: form.scope,
        asset_ids: form.scope === 'selected' ? selectedAssetIds : [],
        strategy: form.strategy,
      }),
    onSuccess: (session) => {
      toast.success(`Session "${session.name}" created`)
      onCreated(session)
    },
    onError: () => toast.error('Failed to create session'),
  })

  const set = <K extends keyof SessionSetupForm>(k: K, v: SessionSetupForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div
        className="card w-[460px] max-w-[95vw] p-6 space-y-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-text-primary">Create Ranking Session</h2>
          <button className="btn-ghost btn-icon" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {/* Session name */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-text-secondary uppercase tracking-wide">
            Session Name
          </label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            className="w-full px-3 py-2 text-sm rounded-md border border-border bg-surface-elevated text-text-primary placeholder:text-text-secondary focus:outline-none focus:ring-1 focus:ring-accent"
            placeholder="e.g. Round 1 Ranking"
          />
        </div>

        {/* Engine */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-text-secondary uppercase tracking-wide">
            Rating Engine
          </label>
          <div className="flex gap-3">
            {(
              [
                { value: 'openskill', label: 'TrueSkill (OpenSkill)', desc: 'Uncertainty-aware, recommended' },
                { value: 'elo', label: 'Elo', desc: 'Classic rating system' },
              ] as const
            ).map((opt) => (
              <label
                key={opt.value}
                className={clsx(
                  'flex-1 flex items-start gap-2.5 p-3 rounded-lg border cursor-pointer transition-colors',
                  form.engine === opt.value
                    ? 'border-accent bg-accent/10'
                    : 'border-border hover:border-border/80 hover:bg-surface-elevated'
                )}
              >
                <input
                  type="radio"
                  name="engine"
                  value={opt.value}
                  checked={form.engine === opt.value}
                  onChange={() => set('engine', opt.value)}
                  className="mt-0.5 accent-[var(--accent)]"
                />
                <div>
                  <div className="text-sm font-medium text-text-primary">{opt.label}</div>
                  <div className="text-[11px] text-text-secondary mt-0.5">{opt.desc}</div>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Scope */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-text-secondary uppercase tracking-wide">
            Scope
          </label>
          <div className="flex gap-2">
            {([
              { value: 'all', label: 'All Assets' },
              ...(selectedAssetIds.length > 0
                ? [{ value: 'selected' as const, label: `Selected (${selectedAssetIds.length})` }]
                : []),
            ] as const).map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => set('scope', opt.value)}
                className={clsx(
                  'btn btn-sm flex-1 transition-colors',
                  form.scope === opt.value
                    ? 'btn-primary'
                    : 'btn-secondary'
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
          {selectedAssetIds.length === 0 ? (
            <p className="text-[11px] text-text-secondary">
              Select assets in Gallery first if you want to rank a focused subset.
            </p>
          ) : (
            <p className="text-[11px] text-text-secondary">
              Selected mode ranks only the assets currently selected elsewhere in the app.
            </p>
          )}
        </div>

        {/* Strategy */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-text-secondary uppercase tracking-wide">
            Pair Selection Strategy
          </label>
          <div className="space-y-1.5">
            {(
              [
                {
                  value: 'uncertainty',
                  label: 'Uncertainty-based',
                  desc: 'Prioritize pairs with high uncertainty — most informative (recommended)',
                },
                {
                  value: 'random',
                  label: 'Random',
                  desc: 'Random pair selection',
                },
                {
                  value: 'balanced',
                  label: 'Balanced',
                  desc: 'Smart pair ordering adapted from image-ranker to compare close, under-ranked candidates',
                },
              ] as const
            ).map((opt) => (
              <label
                key={opt.value}
                className={clsx(
                  'flex items-start gap-2.5 p-2.5 rounded-lg border cursor-pointer transition-colors',
                  form.strategy === opt.value
                    ? 'border-accent bg-accent/10'
                    : 'border-border hover:bg-surface-elevated'
                )}
              >
                <input
                  type="radio"
                  name="strategy"
                  value={opt.value}
                  checked={form.strategy === opt.value}
                  onChange={() => set('strategy', opt.value)}
                  className="mt-0.5 accent-[var(--accent)]"
                />
                <div>
                  <span className="text-sm font-medium text-text-primary">{opt.label}</span>
                  {opt.value === 'uncertainty' && (
                    <span className="ml-1.5 text-[10px] text-accent font-medium bg-accent/15 px-1.5 py-0.5 rounded">
                      Recommended
                    </span>
                  )}
                  <p className="text-[11px] text-text-secondary mt-0.5">{opt.desc}</p>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-3 pt-1">
          <button className="btn btn-secondary flex-1" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary flex-1"
            disabled={
              !form.name.trim()
              || createMutation.isPending
              || (form.scope === 'selected' && selectedAssetIds.length === 0)
            }
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? (
              <>
                <RefreshCw size={13} className="animate-spin" />
                Creating…
              </>
            ) : (
              <>
                <Plus size={13} />
                Start Session
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── AI Judge Drawer ────────────────────────────────────────────────────────────

interface AIJudgeDrawerProps {
  result: AIJudgeComparisonResult
  assetA: RankingAssetPair['asset_a']
  assetB: RankingAssetPair['asset_b']
  onClose: () => void
  onAccept: (winnerId: string, loserId: string, draw: boolean) => void
}
function AIJudgeDrawer({ result, assetA, assetB, onClose, onAccept }: AIJudgeDrawerProps) {
  const winner = result.winner === 'A' ? assetA : result.winner === 'B' ? assetB : null
  const loser = result.winner === 'A' ? assetB : result.winner === 'B' ? assetA : null

  const marginColor =
    result.margin === 'clear'
      ? 'text-green-400'
      : result.margin === 'slight'
      ? 'text-yellow-400'
      : 'text-text-secondary'

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 flex flex-col bg-[#1a1a2e] border-t border-border shadow-2xl max-h-[55vh] animate-slide-up">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-3 border-b border-border shrink-0">
        <Bot size={16} className="text-accent" />
        <h3 className="font-semibold text-sm text-text-primary">AI Judge Result</h3>
        <span
          className={clsx(
            'text-xs px-2 py-0.5 rounded font-medium border',
            result.confidence === 'high'
              ? 'bg-green-900/40 text-green-300 border-green-700/40'
              : result.confidence === 'medium'
              ? 'bg-yellow-900/40 text-yellow-300 border-yellow-700/40'
              : 'bg-red-900/40 text-red-300 border-red-700/40'
          )}
        >
          {result.confidence} confidence
        </span>
        <span className={clsx('text-xs font-medium ml-1', marginColor)}>
          {result.margin} margin
        </span>
        <div className="flex-1" />
        <button className="btn-ghost btn-icon" onClick={onClose}>
          <X size={15} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {/* Winner */}
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-green-400" />
          <span className="text-sm font-medium text-text-primary">
            {result.winner === 'draw' ? (
              'Draw — both assets are comparable'
            ) : (
              <>
                <span className="text-green-400 font-semibold">{result.winner}</span> wins
                {winner && (
                  <span className="text-text-secondary ml-2 font-normal text-xs">
                    ({winner.filename})
                  </span>
                )}
              </>
            )}
          </span>
        </div>

        {/* Reasoning */}
        <p className="text-sm text-text-secondary leading-relaxed">{result.overall_reasoning}</p>

        {/* Dimension breakdown */}
        {Object.keys(result.dimensions).length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-text-secondary uppercase tracking-wide">
              Dimension Breakdown
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {Object.entries(result.dimensions).map(([dim, val]) => (
                <div key={dim} className="bg-surface rounded-lg px-3 py-2 space-y-0.5">
                  <p className="text-[10px] text-text-secondary capitalize">
                    {dim.replace(/_/g, ' ')}
                  </p>
                  <p className="text-xs font-medium text-text-primary">
                    {val.winner}{' '}
                    <span className="font-normal text-text-secondary">— {val.reason}</span>
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Strengths */}
        <div className="grid grid-cols-2 gap-4">
          {result.a_strengths.length > 0 && (
            <div>
              <p className="text-xs font-medium text-text-secondary mb-1">A Strengths</p>
              <ul className="space-y-0.5">
                {result.a_strengths.map((s, i) => (
                  <li key={i} className="text-xs text-text-secondary flex gap-1.5">
                    <span className="text-green-400 mt-0.5">+</span> {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {result.b_strengths.length > 0 && (
            <div>
              <p className="text-xs font-medium text-text-secondary mb-1">B Strengths</p>
              <ul className="space-y-0.5">
                {result.b_strengths.map((s, i) => (
                  <li key={i} className="text-xs text-text-secondary flex gap-1.5">
                    <span className="text-green-400 mt-0.5">+</span> {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* Footer actions */}
      <div className="flex items-center gap-3 px-5 py-3 border-t border-border shrink-0">
        <span className="text-xs text-text-secondary">Accept AI verdict?</span>
        <div className="flex gap-2">
          {result.winner !== 'draw' && winner && loser && (
            <button
              className="btn btn-sm btn-primary"
              onClick={() => onAccept(winner.id, loser.id, false)}
            >
              <CheckCircle size={12} />
              Accept — {result.winner} wins
            </button>
          )}
          {result.winner === 'draw' && (
            <button
              className="btn btn-sm btn-primary"
              onClick={() => onAccept(assetA.id, assetB.id, true)}
            >
              <CheckCircle size={12} />
              Accept Draw
            </button>
          )}
          <button className="btn btn-sm btn-ghost" onClick={onClose}>
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Tab: Arena ─────────────────────────────────────────────────────────────────

interface ArenaTabProps {
  projectId: string
}
function ArenaTab({ projectId }: ArenaTabProps) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const selectedIds = useAssetStore((state) => state.selectedIds)
  const selectedAssetIds = Array.from(selectedIds)

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [showSetupModal, setShowSetupModal] = useState(false)
  const [aiDrawer, setAiDrawer] = useState<AIJudgeComparisonResult | null>(null)
  const [currentPair, setCurrentPair] = useState<RankingAssetPair | null>(null)
  const [flash, setFlash] = useState<{ a: 'winner' | 'loser' | null; b: 'winner' | 'loser' | null }>({
    a: null,
    b: null,
  })
  const comparisonStartRef = useRef<number>(Date.now())

  // Sessions
  const { data: sessions = [], isLoading: sessionsLoading } = useQuery({
    queryKey: ['ranking-sessions', projectId],
    queryFn: () => rankingApi.listSessions(projectId),
    enabled: !!projectId,
  })

  // Auto-select first session
  useEffect(() => {
    if (!selectedSessionId && sessions.length > 0) {
      setSelectedSessionId(sessions[0].id)
    }
  }, [sessions, selectedSessionId])

  const activeSession = sessions.find((s) => s.id === selectedSessionId) ?? null

  // Next pair
  const {
    data: pair,
    isLoading: pairLoading,
    refetch: refetchPair,
    isFetching: pairFetching,
  } = useQuery({
    queryKey: ['ranking-pair', selectedSessionId, activeSession?.selection_strategy],
    queryFn: () => rankingApi.getNextPair(selectedSessionId!, activeSession?.selection_strategy ?? 'uncertainty'),
    enabled: !!selectedSessionId && !!activeSession,
    staleTime: 0,
    gcTime: 0,
  })

  useEffect(() => {
    if (pair) {
      setCurrentPair(pair)
      comparisonStartRef.current = Date.now()
    }
  }, [pair])

  // Record comparison
  const compareMutation = useMutation({
    mutationFn: ({
      winnerId,
      loserId,
      draw,
    }: {
      winnerId: string
      loserId: string
      draw: boolean
    }) => {
      const elapsed = Date.now() - comparisonStartRef.current
      return rankingApi.recordComparison(selectedSessionId!, winnerId, loserId, draw, {
        decided_by: 'human',
        comparison_time_ms: elapsed,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ranking-sessions', projectId] })
      queryClient.invalidateQueries({ queryKey: ['leaderboard', selectedSessionId] })
      setTimeout(() => {
        setFlash({ a: null, b: null })
        refetchPair()
      }, 350)
    },
    onError: () => toast.error('Failed to record comparison'),
  })

  const skipMutation = useMutation({
    mutationFn: () => {
      if (!currentPair || !selectedSessionId) throw new Error('No pair')
      return rankingApi.skipPair(selectedSessionId, currentPair.asset_a.id, currentPair.asset_b.id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ranking-sessions', projectId] })
      refetchPair()
    },
    onError: () => toast.error('Failed to skip pair'),
  })

  const undoMutation = useMutation({
    mutationFn: () => {
      if (!selectedSessionId) throw new Error('No session')
      return rankingApi.undoLastComparison(selectedSessionId)
    },
    onSuccess: () => {
      toast.success('Reverted last comparison')
      queryClient.invalidateQueries({ queryKey: ['ranking-sessions', projectId] })
      queryClient.invalidateQueries({ queryKey: ['leaderboard', selectedSessionId] })
      refetchPair()
    },
    onError: () => toast.error('No comparison available to undo'),
  })

  const handlePick = useCallback(
    (winnerId: string, loserId: string) => {
      if (!currentPair || compareMutation.isPending) return
      const isA = winnerId === currentPair.asset_a.id
      setFlash({ a: isA ? 'winner' : 'loser', b: isA ? 'loser' : 'winner' })
      compareMutation.mutate({ winnerId, loserId, draw: false })
    },
    [currentPair, compareMutation]
  )

  const handleDraw = useCallback(() => {
    if (!currentPair || compareMutation.isPending) return
    setFlash({ a: null, b: null })
    compareMutation.mutate({
      winnerId: currentPair.asset_a.id,
      loserId: currentPair.asset_b.id,
      draw: true,
    })
  }, [currentPair, compareMutation])

  const handleSkip = useCallback(() => {
    if (compareMutation.isPending || skipMutation.isPending) return
    skipMutation.mutate()
  }, [compareMutation.isPending, skipMutation, skipMutation.isPending])

  const handleUndo = useCallback(() => {
    if (compareMutation.isPending || undoMutation.isPending) return
    undoMutation.mutate()
  }, [compareMutation.isPending, undoMutation, undoMutation.isPending])

  // AI compare
  const aiCompareMutation = useMutation({
    mutationFn: () => {
      if (!currentPair || !selectedSessionId) throw new Error('No pair')
      return rankingApi.aiCompare(selectedSessionId, currentPair.asset_a.id, currentPair.asset_b.id)
    },
    onSuccess: (result) => {
      setAiDrawer(result)
    },
    onError: () => toast.error('AI comparison failed'),
  })

  const handleAiAccept = useCallback(
    (winnerId: string, loserId: string, draw: boolean) => {
      if (!currentPair) return
      const isA = winnerId === currentPair.asset_a.id
      setFlash({ a: isA ? 'winner' : 'loser', b: isA ? 'loser' : 'winner' })
      setAiDrawer(null)
      compareMutation.mutate({ winnerId, loserId, draw })
    },
    [currentPair, compareMutation]
  )

  // Keyboard shortcuts
  useEffect(() => {
    if (!currentPair) return
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (compareMutation.isPending || pairFetching) return
      const key = e.key.toLowerCase()
      if (key === 'a') handlePick(currentPair.asset_a.id, currentPair.asset_b.id)
      else if (key === 'd') handlePick(currentPair.asset_b.id, currentPair.asset_a.id)
      else if (key === 's') handleDraw()
      else if (key === ' ') {
        e.preventDefault()
        handleSkip()
      }
      else if (key === 'z') {
        e.preventDefault()
        handleUndo()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [currentPair, handlePick, handleDraw, handleSkip, handleUndo, compareMutation.isPending, pairFetching])

  const isWorking = compareMutation.isPending || skipMutation.isPending || undoMutation.isPending || pairFetching || pairLoading

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Session header */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-surface shrink-0 flex-wrap gap-y-2">
        {sessionsLoading ? (
          <div className="text-xs text-text-secondary">Loading sessions…</div>
        ) : (
          <select
            value={selectedSessionId ?? ''}
            onChange={(e) => setSelectedSessionId(e.target.value || null)}
            className="text-sm py-1 px-2 rounded border border-border bg-surface-elevated text-text-primary min-w-[200px]"
            style={{ width: 'auto' }}
            disabled={sessions.length === 0}
          >
            {sessions.length === 0 ? (
              <option value="">No sessions</option>
            ) : (
              sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))
            )}
          </select>
        )}

        {activeSession && (
          <>
            <span className="badge text-[11px] px-2 py-0.5 rounded border border-border bg-surface-elevated text-text-secondary">
              {activeSession.ranking_algorithm === 'openskill' ? 'TrueSkill' : 'Elo'}
            </span>
            <span className="badge text-[11px] px-2 py-0.5 rounded border border-border bg-surface-elevated text-text-secondary">
              {activeSession.selection_strategy === 'balanced'
                ? 'Smart Balanced'
                : activeSession.selection_strategy === 'random'
                ? 'Random'
                : 'Uncertainty'}
            </span>
            {activeSession.asset_scope !== 'all' && (
              <span className="text-xs text-text-secondary">
                Scope: {activeSession.asset_scope}
                {activeSession.asset_ids_count > 0 ? ` (${activeSession.asset_ids_count})` : ''}
              </span>
            )}
            <span className="text-xs text-text-secondary">
              {activeSession.total_comparisons} comparisons
            </span>
            {activeSession.skipped_pairs_count > 0 && (
              <span className="text-xs text-text-secondary">
                {activeSession.skipped_pairs_count} skipped
              </span>
            )}
          </>
        )}

        <div className="flex-1" />

        <button
          className="btn btn-sm btn-primary"
          onClick={() => setShowSetupModal(true)}
        >
          <Plus size={13} />
          New Session
        </button>
      </div>

      {/* No sessions state */}
      {!sessionsLoading && sessions.length === 0 ? (
        <div className="flex flex-col items-center justify-center flex-1 gap-4 text-text-secondary">
          <Trophy size={48} className="opacity-20" />
          <p className="text-sm font-medium">No sessions yet. Create one to start ranking.</p>
          <button className="btn btn-primary btn-sm" onClick={() => setShowSetupModal(true)}>
            <Plus size={13} />
            Create Session
          </button>
        </div>
      ) : (
        <div className="flex-1 flex flex-col overflow-y-auto px-4 py-4 gap-4">
          {/* Arena */}
          {isWorking && !currentPair ? (
            <div className="flex items-center justify-center flex-1 gap-2 text-text-secondary">
              <RefreshCw size={20} className="animate-spin" />
              <span>{compareMutation.isPending ? 'Updating ratings…' : 'Loading pair…'}</span>
            </div>
          ) : currentPair ? (
            <>
              {/* Cards */}
              <div className="flex gap-4 flex-1 min-h-0">
                <ArenaCard
                  asset={currentPair.asset_a}
                  label="A"
                  keyHint="A"
                  onPick={() => handlePick(currentPair.asset_a.id, currentPair.asset_b.id)}
                  disabled={isWorking}
                  flash={flash.a}
                />
                <div className="flex flex-col items-center justify-center gap-2 text-text-secondary shrink-0 w-8">
                  <div className="text-base font-bold">vs</div>
                </div>
                <ArenaCard
                  asset={currentPair.asset_b}
                  label="B"
                  keyHint="D"
                  onPick={() => handlePick(currentPair.asset_b.id, currentPair.asset_a.id)}
                  disabled={isWorking}
                  flash={flash.b}
                />
              </div>

              {/* Action row */}
              <div className="flex items-center justify-center gap-2 flex-wrap shrink-0">
                <button
                  className="btn btn-primary"
                  onClick={() => handlePick(currentPair.asset_a.id, currentPair.asset_b.id)}
                  disabled={isWorking}
                >
                  <span>← A Wins</span>
                  <kbd className="ml-1.5 text-[10px] opacity-70 border border-white/20 rounded px-1">A</kbd>
                </button>
                <button
                  className="btn btn-secondary"
                  onClick={handleDraw}
                  disabled={isWorking}
                >
                  <span>= Draw</span>
                  <kbd className="ml-1.5 text-[10px] opacity-70 border border-border rounded px-1">S</kbd>
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() => handlePick(currentPair.asset_b.id, currentPair.asset_a.id)}
                  disabled={isWorking}
                >
                  <span>B Wins →</span>
                  <kbd className="ml-1.5 text-[10px] opacity-70 border border-white/20 rounded px-1">D</kbd>
                </button>
                <button
                  className="btn btn-ghost"
                  onClick={handleSkip}
                  disabled={isWorking}
                >
                  <SkipForward size={13} />
                  <span>Skip</span>
                  <kbd className="ml-1 text-[10px] opacity-70 border border-border rounded px-1">Space</kbd>
                </button>
                <button
                  className="btn btn-ghost"
                  onClick={handleUndo}
                  disabled={isWorking || !activeSession || activeSession.total_comparisons === 0}
                >
                  <RotateCcw size={13} />
                  <span>Undo</span>
                  <kbd className="ml-1 text-[10px] opacity-70 border border-border rounded px-1">Z</kbd>
                </button>
                <button
                  className="btn btn-ghost"
                  onClick={() => aiCompareMutation.mutate()}
                  disabled={isWorking || aiCompareMutation.isPending}
                >
                  {aiCompareMutation.isPending ? (
                    <RefreshCw size={13} className="animate-spin" />
                  ) : (
                    <Bot size={13} />
                  )}
                  AI Judge this pair
                </button>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center flex-1 gap-3 text-text-secondary">
              <Trophy size={48} className="opacity-20" />
              <p className="text-sm">No pairs available — add more images to rank</p>
            </div>
          )}
        </div>
      )}

      {/* Setup modal */}
      {showSetupModal && (
        <SessionSetupModal
          projectId={projectId}
          selectedAssetIds={selectedAssetIds}
          onClose={() => setShowSetupModal(false)}
          onCreated={(session) => {
            queryClient.invalidateQueries({ queryKey: ['ranking-sessions', projectId] })
            setSelectedSessionId(session.id)
            setShowSetupModal(false)
          }}
        />
      )}

      {/* AI drawer */}
      {aiDrawer && currentPair && (
        <AIJudgeDrawer
          result={aiDrawer}
          assetA={currentPair.asset_a}
          assetB={currentPair.asset_b}
          onClose={() => setAiDrawer(null)}
          onAccept={handleAiAccept}
        />
      )}
    </div>
  )
}

// ── Tab: Leaderboard ──────────────────────────────────────────────────────────

interface LeaderboardTabProps {
  projectId: string
}
function LeaderboardTab({ projectId }: LeaderboardTabProps) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [previewEntry, setPreviewEntry] = useState<LeaderboardEntry | null>(null)
  const leaderboardScrollRef = useRef<HTMLDivElement>(null)

  const { data: sessions = [] } = useQuery({
    queryKey: ['ranking-sessions', projectId],
    queryFn: () => rankingApi.listSessions(projectId),
    enabled: !!projectId,
  })

  useEffect(() => {
    if (!selectedSessionId && sessions.length > 0) {
      setSelectedSessionId(sessions[0].id)
    }
  }, [sessions, selectedSessionId])

  const { data: leaderboard = [], isLoading } = useQuery({
    queryKey: ['leaderboard', selectedSessionId],
    queryFn: () => rankingApi.getLeaderboard(selectedSessionId!, 200),
    enabled: !!selectedSessionId,
  })

  const applyMutation = useMutation({
    mutationFn: () => rankingApi.applyRankings(selectedSessionId!),
    onSuccess: () => {
      toast.success('Rankings applied to assets')
      queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
    onError: () => toast.error('Failed to apply rankings'),
  })

  const handleExport = () => {
    const data = JSON.stringify(leaderboard, null, 2)
    const blob = new Blob([data], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `leaderboard-${selectedSessionId ?? 'export'}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const total = leaderboard.length

  const rowVirtualizer = useVirtualizer({
    count: leaderboard.length,
    getScrollElement: () => leaderboardScrollRef.current,
    estimateSize: () => 44,
    overscan: 10,
  })

  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-surface shrink-0 flex-wrap gap-y-2">
          <select
            value={selectedSessionId ?? ''}
            onChange={(e) => setSelectedSessionId(e.target.value || null)}
            className="text-sm py-1 px-2 rounded border border-border bg-surface-elevated text-text-primary"
            style={{ width: 'auto' }}
            disabled={sessions.length === 0}
          >
            {sessions.length === 0 ? (
              <option value="">No sessions</option>
            ) : (
              sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))
            )}
          </select>

          <div className="flex-1" />

          <button
            className="btn btn-sm btn-secondary"
            onClick={handleExport}
            disabled={leaderboard.length === 0}
          >
            <Download size={13} />
            Export JSON
          </button>
          <button
            className="btn btn-sm btn-primary"
            onClick={() => applyMutation.mutate()}
            disabled={!selectedSessionId || applyMutation.isPending || leaderboard.length === 0}
          >
            {applyMutation.isPending ? (
              <RefreshCw size={13} className="animate-spin" />
            ) : (
              <CheckCircle size={13} />
            )}
            Apply Rankings to Assets
          </button>
        </div>

        {/* Table */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {isLoading ? (
            <div className="flex items-center justify-center h-full gap-2 text-text-secondary">
              <RefreshCw size={18} className="animate-spin" />
              <span>Loading leaderboard…</span>
            </div>
          ) : leaderboard.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-text-secondary">
              <Trophy size={40} className="opacity-20" />
              <p className="text-sm">Complete some comparisons to see the leaderboard</p>
            </div>
          ) : (
            <>
              <table className="w-full text-sm">
                <thead className="bg-surface border-b border-border">
                  <tr>
                    <th className="text-left px-3 py-2 text-xs font-medium text-text-secondary w-12">Rank</th>
                    <th className="text-left px-3 py-2 text-xs font-medium text-text-secondary w-14">Thumb</th>
                    <th className="text-left px-3 py-2 text-xs font-medium text-text-secondary">Filename</th>
                    <th className="text-right px-3 py-2 text-xs font-medium text-text-secondary w-20">
                      μ Score
                    </th>
                    <th className="text-right px-3 py-2 text-xs font-medium text-text-secondary w-16">σ</th>
                    <th className="text-right px-3 py-2 text-xs font-medium text-text-secondary w-20">
                      Comparisons
                    </th>
                    <th className="text-left px-3 py-2 text-xs font-medium text-text-secondary w-28">
                      Confidence
                    </th>
                    <th className="text-right px-3 py-2 text-xs font-medium text-text-secondary w-20">
                      AI Score
                    </th>
                  </tr>
                </thead>
              </table>
              <div ref={leaderboardScrollRef} className="flex-1 overflow-y-auto">
                <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
                  {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                    const entry = leaderboard[virtualRow.index]
                    const rankColor = scoreColorClass(entry.mu, total, entry.rank)
                    const isSelected = previewEntry?.asset_id === entry.asset_id
                    return (
                      <div
                        key={entry.asset_id}
                        onClick={() => setPreviewEntry(isSelected ? null : entry)}
                        className={clsx(
                          'flex items-center border-b border-border/50 cursor-pointer transition-colors hover:bg-surface-elevated',
                          isSelected && 'bg-accent/10'
                        )}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          height: virtualRow.size,
                          transform: `translateY(${virtualRow.start}px)`,
                        }}
                      >
                        <div className={clsx('px-3 py-2 font-bold tabular-nums text-sm w-12 shrink-0', rankColor)}>
                          {entry.rank}
                        </div>
                        <div className="px-3 py-1.5 w-14 shrink-0">
                          <img
                            src={
                              entry.thumbnail_url ??
                              assetsApi.thumbnailUrl(entry.asset_id, 128)
                            }
                            alt={entry.filename}
                            className="w-10 h-10 object-cover rounded bg-surface-elevated"
                          />
                        </div>
                        <div className={clsx('px-3 py-2 text-xs truncate flex-1 min-w-0', rankColor)}>
                          {entry.filename}
                        </div>
                        <div className={clsx('px-3 py-2 text-right font-mono font-medium tabular-nums w-20 shrink-0', rankColor)}>
                          {entry.mu.toFixed(2)}
                        </div>
                        <div className="px-3 py-2 text-right text-xs text-text-secondary tabular-nums w-16 shrink-0">
                          {entry.sigma != null ? entry.sigma.toFixed(2) : '—'}
                        </div>
                        <div className="px-3 py-2 text-right text-xs text-text-secondary tabular-nums w-20 shrink-0">
                          {entry.comparisons}
                        </div>
                        <div className="px-3 py-2 w-28 shrink-0">
                          {entry.sigma != null ? (
                            <ConfidenceBar sigma={entry.sigma} />
                          ) : (
                            <span className="text-text-secondary text-xs">—</span>
                          )}
                        </div>
                        <div className="px-3 py-2 text-right w-20 shrink-0">
                          {entry.ai_composite != null ? (
                            <Score value={entry.ai_composite} size="sm" />
                          ) : (
                            <span className="text-text-secondary text-xs">—</span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Side preview */}
      {previewEntry && (
        <div className="w-64 border-l border-border flex flex-col overflow-hidden shrink-0">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
            <span className="text-xs font-medium text-text-secondary">Preview</span>
            <button className="btn-ghost btn-icon" onClick={() => setPreviewEntry(null)}>
              <X size={13} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            <img
              src={
                previewEntry.thumbnail_url ??
                assetsApi.thumbnailUrl(previewEntry.asset_id, 512)
              }
              alt={previewEntry.filename}
              className="w-full rounded-lg object-cover"
              style={{ aspectRatio: '1' }}
            />
            <div className="space-y-1.5 text-xs text-text-secondary">
              <p className="text-text-primary font-medium truncate">{previewEntry.filename}</p>
              <div className="flex justify-between">
                <span>Rank</span>
                <span className="font-medium text-text-primary">#{previewEntry.rank}</span>
              </div>
              <div className="flex justify-between">
                <span>μ score</span>
                <span className="font-mono font-medium text-text-primary">
                  {previewEntry.mu.toFixed(3)}
                </span>
              </div>
              {previewEntry.sigma != null && (
                <div className="flex justify-between">
                  <span>σ</span>
                  <span className="font-mono text-text-primary">
                    {previewEntry.sigma.toFixed(3)}
                  </span>
                </div>
              )}
              <div className="flex justify-between">
                <span>Comparisons</span>
                <span className="text-text-primary">{previewEntry.comparisons}</span>
              </div>
              {previewEntry.sigma != null && (
                <>
                  <p className="text-text-secondary pt-1">Confidence</p>
                  <ConfidenceBar sigma={previewEntry.sigma} />
                </>
              )}
              {previewEntry.ai_composite != null && (
                <div className="flex justify-between items-center pt-1">
                  <span>AI Score</span>
                  <Score value={previewEntry.ai_composite} size="sm" />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── AI Judge card ──────────────────────────────────────────────────────────────

interface AIJudgeCardProps {
  assetId: string
  filename: string
  result: AIJudgeResult
  onReJudge: (id: string) => void
  isJudging: boolean
}
function AIJudgeCard({ assetId, filename, result, onReJudge, isJudging }: AIJudgeCardProps) {
  const [expanded, setExpanded] = useState(false)

  const compositeColor = compositeScoreColor(result.composite)
  const scorePercent = Math.round(result.composite * 100)

  const dimensionLabels: Record<string, string> = {
    technical_quality: 'Technical',
    aesthetic_quality: 'Aesthetic',
    face_clarity: 'Face Clarity',
    pose_usefulness: 'Pose',
    expression_quality: 'Expression',
    background_usefulness: 'Background',
    uniqueness: 'Uniqueness',
    training_value: 'Training Value',
  }

  return (
    <div
      className={clsx(
        'card overflow-hidden flex flex-col transition-all',
        result.needs_human_review && 'ring-1 ring-yellow-500/40'
      )}
    >
      {/* Thumbnail */}
      <div className="relative overflow-hidden" style={{ aspectRatio: '1' }}>
        <img
          src={assetsApi.thumbnailUrl(assetId, 512)}
          alt={filename}
          className="w-full h-full object-cover"
          draggable={false}
        />
        {result.needs_human_review && (
          <div className="absolute top-2 left-2">
            <span className="flex items-center gap-1 text-[10px] bg-yellow-900/80 text-yellow-300 border border-yellow-700/50 rounded px-1.5 py-0.5 font-medium">
              <AlertTriangle size={9} />
              Review
            </span>
          </div>
        )}
      </div>

      {/* Body */}
      <div className="p-3 flex flex-col gap-2 flex-1">
        <p className="text-xs text-text-secondary truncate">{filename}</p>

        {/* Score + recommendation */}
        <div className="flex items-center gap-2">
          <span
            className="text-2xl font-bold tabular-nums"
            style={{ color: compositeColor }}
          >
            {scorePercent}
          </span>
          <div className="flex flex-col gap-1">
            {recommendationBadge(result.recommendation)}
            <span className="text-[10px] text-text-secondary capitalize">
              {result.confidence} conf.
            </span>
          </div>
        </div>

        {/* Expand toggle */}
        <button
          className="flex items-center gap-1 text-[11px] text-text-secondary hover:text-text-primary transition-colors"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {expanded ? 'Hide details' : 'Show details'}
        </button>

        {/* Dimension breakdown */}
        {expanded && (
          <div className="space-y-1.5 pt-1">
            {Object.entries(result.scores).map(([key, val]) => (
              <div key={key} className="space-y-0.5">
                <div className="flex justify-between text-[10px]">
                  <span className="text-text-secondary">{dimensionLabels[key] ?? key}</span>
                  {val.not_applicable ? (
                    <span className="text-text-secondary italic">N/A</span>
                  ) : (
                    <span
                      className="font-medium"
                      style={{ color: compositeScoreColor(val.score) }}
                    >
                      {Math.round(val.score * 100)}
                    </span>
                  )}
                </div>
                {!val.not_applicable && (
                  <div className="h-1 bg-surface-elevated rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.round(val.score * 100)}%`,
                        background: compositeScoreColor(val.score),
                      }}
                    />
                  </div>
                )}
                {val.reason && (
                  <p className="text-[10px] text-text-secondary leading-tight">{val.reason}</p>
                )}
              </div>
            ))}

            {/* Strengths / weaknesses */}
            {result.strengths.length > 0 && (
              <div className="pt-1">
                <p className="text-[10px] font-medium text-green-400 mb-0.5">Strengths</p>
                {result.strengths.map((s, i) => (
                  <p key={i} className="text-[10px] text-text-secondary">
                    + {s}
                  </p>
                ))}
              </div>
            )}
            {result.weaknesses.length > 0 && (
              <div className="pt-1">
                <p className="text-[10px] font-medium text-red-400 mb-0.5">Weaknesses</p>
                {result.weaknesses.map((s, i) => (
                  <p key={i} className="text-[10px] text-text-secondary">
                    - {s}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Re-judge button */}
        <button
          className="btn btn-ghost btn-sm mt-auto"
          onClick={() => onReJudge(assetId)}
          disabled={isJudging}
        >
          {isJudging ? <RefreshCw size={11} className="animate-spin" /> : <Bot size={11} />}
          Re-judge
        </button>
      </div>
    </div>
  )
}

// ── Tab: AI Judge ─────────────────────────────────────────────────────────────

interface AIJudgeTabProps {
  projectId: string
}
function AIJudgeTab({ projectId }: AIJudgeTabProps) {
  const toast = useToast()
  const queryClient = useQueryClient()

  const [filter, setFilter] = useState<AIFilter>('all')
  const [sort, setSort] = useState<AISort>('composite')
  const [judgeResults, setJudgeResults] = useState<Map<string, AIJudgeResult>>(new Map())
  const [judgingId, setJudgingId] = useState<string | null>(null)
  const [batchJobId, setBatchJobId] = useState<string | null>(null)
  const [batchProgress, setBatchProgress] = useState<number>(0)

  // Load assets to judge
  const { data: assetData, isLoading: assetsLoading } = useQuery({
    queryKey: ['assets-for-judge', projectId],
    queryFn: () =>
      assetsApi.list(projectId, {
        page: 1,
        page_size: 100,
        sort_by: 'composite_score',
        sort_dir: 'desc',
      }),
    enabled: !!projectId,
  })

  const assets = assetData?.items ?? []

  // Batch AI judge
  const batchMutation = useMutation({
    mutationFn: () => rankingApi.aiJudgeBatch(projectId),
    onSuccess: (res) => {
      toast.info(`AI judging ${res.asset_count} assets…`)
      setBatchJobId(res.job_id)
      setBatchProgress(0)
    },
    onError: () => toast.error('Failed to start batch AI judge'),
  })

  // Poll batch job
  useEffect(() => {
    if (!batchJobId) return
    const interval = setInterval(async () => {
      try {
        const { default: api } = await import('@/hooks/useApi')
        const job = await api.get(`/api/jobs/${batchJobId}`).then((r) => r.data)
        setBatchProgress(job.progress ?? 0)
        if (job.status === 'done' || job.status === 'failed') {
          setBatchJobId(null)
          if (job.status === 'done') {
            toast.success('Batch AI judging complete')
            queryClient.invalidateQueries({ queryKey: ['assets-for-judge', projectId] })
          } else {
            toast.error('Batch AI judging failed')
          }
        }
      } catch {
        // ignore poll errors
      }
    }, 1500)
    return () => clearInterval(interval)
  }, [batchJobId, projectId, queryClient, toast])

  // Single asset judge
  const judgeOne = useCallback(
    async (assetId: string) => {
      setJudgingId(assetId)
      try {
        const result = await rankingApi.aiJudgeAsset(assetId)
        setJudgeResults((m) => {
          const next = new Map(m)
          next.set(assetId, result)
          return next
        })
      } catch {
        toast.error('AI judging failed for this asset')
      } finally {
        setJudgingId(null)
      }
    },
    [toast]
  )

  // Merge stored results with asset composite scores
  const assetResults = assets
    .map((a) => {
      const judgeResult = judgeResults.get(a.id)
      return { asset: a, result: judgeResult ?? null }
    })
    .filter(({ result }) => {
      if (filter === 'all') return true
      if (!result) return false
      if (filter === 'needs_review') return result.needs_human_review
      return result.recommendation === filter
    })
    .sort((a, b) => {
      if (!a.result && !b.result) return 0
      if (!a.result) return 1
      if (!b.result) return -1
      if (sort === 'composite') return b.result.composite - a.result.composite
      if (sort === 'training_value')
        return b.result.scores.training_value.score - a.result.scores.training_value.score
      // confidence: high > medium > low
      const order = { high: 3, medium: 2, low: 1 }
      return (order[b.result.confidence] ?? 0) - (order[a.result.confidence] ?? 0)
    })

  const judgedCount = judgeResults.size
  const totalAssets = assets.length

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-surface shrink-0 flex-wrap gap-y-2">
        <div className="flex items-center gap-1.5">
          <Bot size={15} className="text-accent" />
          <span className="text-sm font-medium text-text-primary">AI Judge</span>
          {judgedCount > 0 && (
            <span className="text-xs text-text-secondary ml-1">
              {judgedCount}/{totalAssets} scored
            </span>
          )}
        </div>

        {/* Batch progress */}
        {batchJobId && (
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            <RefreshCw size={11} className="animate-spin" />
            <div className="w-24 h-1.5 bg-surface-elevated rounded-full overflow-hidden">
              <div
                className="h-full bg-accent rounded-full transition-all"
                style={{ width: `${Math.round(batchProgress * 100)}%` }}
              />
            </div>
            <span>{Math.round(batchProgress * 100)}%</span>
          </div>
        )}

        <div className="flex-1" />

        {/* Sort */}
        <div className="flex items-center gap-1.5">
          <ArrowUpDown size={12} className="text-text-secondary" />
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as AISort)}
            className="text-xs py-1 px-2 rounded border border-border bg-surface-elevated text-text-primary"
            style={{ width: 'auto' }}
          >
            <option value="composite">Composite Score</option>
            <option value="training_value">Training Value</option>
            <option value="confidence">Confidence</option>
          </select>
        </div>

        {/* Filter */}
        <div className="flex items-center gap-1">
          {(
            [
              { value: 'all', label: 'All' },
              { value: 'needs_review', label: 'Review' },
              { value: 'keep', label: 'Keep' },
              { value: 'maybe', label: 'Maybe' },
              { value: 'remove', label: 'Remove' },
            ] as const
          ).map((f) => (
            <button
              key={f.value}
              className={clsx(
                'btn btn-sm px-2 py-1 text-xs transition-colors',
                filter === f.value ? 'btn-primary' : 'btn-ghost'
              )}
              onClick={() => setFilter(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>

        <button
          className="btn btn-sm btn-primary"
          onClick={() => batchMutation.mutate()}
          disabled={batchMutation.isPending || !!batchJobId}
        >
          {batchMutation.isPending || batchJobId ? (
            <RefreshCw size={12} className="animate-spin" />
          ) : (
            <Bot size={12} />
          )}
          Batch AI Judge
        </button>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto p-4">
        {assetsLoading ? (
          <div className="flex items-center justify-center h-full gap-2 text-text-secondary">
            <RefreshCw size={18} className="animate-spin" />
            <span>Loading assets…</span>
          </div>
        ) : assetResults.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-text-secondary">
            <Star size={40} className="opacity-20" />
            <p className="text-sm">
              {filter !== 'all'
                ? `No assets match filter "${filter}"`
                : 'No assets to judge. Click "Batch AI Judge" to score all assets.'}
            </p>
            {filter !== 'all' && (
              <button className="btn btn-sm btn-ghost" onClick={() => setFilter('all')}>
                Clear filter
              </button>
            )}
          </div>
        ) : (
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
            {assetResults.map(({ asset, result }) =>
              result ? (
                <AIJudgeCard
                  key={asset.id}
                  assetId={asset.id}
                  filename={asset.filename}
                  result={result}
                  onReJudge={judgeOne}
                  isJudging={judgingId === asset.id}
                />
              ) : (
                // Not-yet-judged card
                <div
                  key={asset.id}
                  className="card overflow-hidden flex flex-col opacity-60 hover:opacity-80 transition-opacity"
                >
                  <div className="relative overflow-hidden" style={{ aspectRatio: '1' }}>
                    <img
                      src={assetsApi.thumbnailUrl(asset.id, 512)}
                      alt={asset.filename}
                      className="w-full h-full object-cover"
                      draggable={false}
                    />
                  </div>
                  <div className="p-3 flex flex-col gap-2">
                    <p className="text-xs text-text-secondary truncate">{asset.filename}</p>
                    {asset.composite_score != null && (
                      <Score value={asset.composite_score} size="sm" showLabel />
                    )}
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => judgeOne(asset.id)}
                      disabled={judgingId === asset.id}
                    >
                      {judgingId === asset.id ? (
                        <RefreshCw size={11} className="animate-spin" />
                      ) : (
                        <Bot size={11} />
                      )}
                      Judge this
                    </button>
                  </div>
                </div>
              )
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Root component ─────────────────────────────────────────────────────────────

export function Ranking() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('arena')
  const activeProject = useProjectStore((s) => s.activeProject)

  if (!activeProject) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-text-secondary">
        <Trophy size={48} className="opacity-20" />
        <p className="text-sm font-medium">Select a project to start ranking</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-center gap-0 border-b border-border bg-surface shrink-0">
        {(
          [
            { id: 'arena', label: 'Arena', icon: <Layers size={14} /> },
            { id: 'leaderboard', label: 'Leaderboard', icon: <Trophy size={14} /> },
            { id: 'ai-judge', label: 'AI Judge', icon: <Bot size={14} /> },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={clsx(
              'flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
              activeTab === tab.id
                ? 'border-accent text-accent bg-accent/5'
                : 'border-transparent text-text-secondary hover:text-text-primary hover:bg-surface-elevated'
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'arena' && <ArenaTab projectId={activeProject.id} />}
        {activeTab === 'leaderboard' && <LeaderboardTab projectId={activeProject.id} />}
        {activeTab === 'ai-judge' && <AIJudgeTab projectId={activeProject.id} />}
      </div>
    </div>
  )
}
