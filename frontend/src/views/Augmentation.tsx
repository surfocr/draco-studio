import React, { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Play, Check, X, ArrowRight, Wand2, LayoutGrid } from 'lucide-react'
import { useProjectStore } from '@/stores/useProjectStore'
import { useAssetStore } from '@/stores/useAssetStore'
import { augmentationApi, assetsApi } from '@/hooks/useApi'
import { useToast } from '@/components/providers/ToastProvider'
import type { AugmentationPlan, AugmentationResult } from '@/types/api'

// ── Types ──────────────────────────────────────────────────────────────────────

type AspectRatio = '1:1' | '4:3' | '3:4' | '16:9' | '9:16' | 'custom'

interface AspectOption {
  label: AspectRatio
  w: number
  h: number
}

const ASPECT_OPTIONS: AspectOption[] = [
  { label: '1:1',    w: 1024, h: 1024 },
  { label: '4:3',    w: 1024, h: 768  },
  { label: '3:4',    w: 768,  h: 1024 },
  { label: '16:9',   w: 1280, h: 720  },
  { label: '9:16',   w: 720,  h: 1280 },
  { label: 'custom', w: 1024, h: 1024 },
]

const PROVIDER_OPTIONS = [
  { value: 'auto',         label: 'Auto (best available)' },
  { value: 'comfyui',      label: 'ComfyUI' },
  { value: 'basic_editor', label: 'Basic Editor' },
]

const TABS = ['Outpaint / Fit', 'Expansion Plan', 'Review Results'] as const
type TabName = typeof TABS[number]

// ── Plan Item ──────────────────────────────────────────────────────────────────

function PlanItem({
  plan,
  onExecute,
  onSkip,
  isExecuting,
}: {
  plan: AugmentationPlan
  onExecute: () => void
  onSkip: () => void
  isExecuting: boolean
}) {
  const benefitPct = Math.round((plan.estimated_benefit ?? 0) * 100)

  return (
    <div className="card p-3">
      <div className="flex gap-3">
        {plan.source_asset_id && (
          <img
            src={assetsApi.thumbnailUrl(plan.source_asset_id, 128)}
            alt=""
            className="w-16 h-16 rounded object-cover border border-[var(--border)] flex-shrink-0"
            onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--accent)]/20 text-[var(--accent)] font-medium uppercase">
              {plan.operation}
            </span>
            <span className="text-xs text-[var(--text-secondary)]">Priority {plan.priority}</span>
          </div>
          <p className="text-sm text-[var(--text-primary)] mb-1">{plan.reason}</p>
          <p className="text-xs text-[var(--text-secondary)] mb-2">
            Gap: <span className="text-[var(--text-primary)]">{plan.gap_addressed}</span>
          </p>
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-secondary)]">Benefit</span>
            <div className="flex-1 h-1.5 rounded-full bg-[var(--border)]">
              <div
                className="h-full rounded-full bg-[var(--accent)]"
                style={{ width: `${benefitPct}%` }}
              />
            </div>
            <span className="text-xs text-[var(--text-secondary)]">{benefitPct}%</span>
          </div>
        </div>
      </div>
      <div className="flex gap-2 mt-3">
        <button
          onClick={onExecute}
          disabled={isExecuting}
          className="btn btn-sm btn-primary flex items-center gap-1 flex-1"
        >
          {isExecuting
            ? <RefreshCw size={12} className="animate-spin" />
            : <Play size={12} />}
          Execute
        </button>
        <button onClick={onSkip} className="btn btn-sm btn-secondary flex items-center gap-1">
          <X size={12} /> Skip
        </button>
      </div>
    </div>
  )
}

// ── Result Card ────────────────────────────────────────────────────────────────

function ResultCard({
  result,
  focused,
  onApprove,
  onReject,
}: {
  result: AugmentationResult
  focused: boolean
  onApprove: () => void
  onReject: () => void
}) {
  const afterPreviewUrl = augmentationApi.previewUrl(result.id)

  const scoreDelta =
    result.before_score != null && result.after_score != null
      ? result.after_score - result.before_score
      : null

  useEffect(() => {
    if (!focused) return
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'a' || e.key === 'A') onApprove()
      if (e.key === 'r' || e.key === 'R') onReject()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [focused, onApprove, onReject])

  return (
    <div className={`card overflow-hidden ${focused ? 'ring-2 ring-[var(--accent)]' : ''}`}>
      <div className="flex">
        <div className="flex-1 relative">
          <span className="absolute top-1 left-1 text-xs bg-black/60 text-white px-1.5 py-0.5 rounded z-10 font-medium">
            BEFORE
          </span>
          <img
            src={assetsApi.thumbnailUrl(result.source_asset_id, 512)}
            alt="before"
            className="w-full aspect-square object-cover"
            onError={e => {
              (e.target as HTMLImageElement).style.display = 'none'
            }}
          />
        </div>
        <div className="flex-shrink-0 flex items-center justify-center w-6">
          <ArrowRight size={14} className="text-[var(--text-secondary)]" />
        </div>
        <div className="flex-1 relative">
          <span className="absolute top-1 left-1 text-xs bg-black/60 text-white px-1.5 py-0.5 rounded z-10 font-medium">
            AFTER
          </span>
          <img
            src={afterPreviewUrl}
            alt="after"
            className="w-full aspect-square object-cover bg-[var(--border)]"
            onError={e => {
              (e.target as HTMLImageElement).style.display = 'none'
            }}
          />
        </div>
      </div>

      <div className="p-3 flex flex-wrap items-center gap-3 text-xs text-[var(--text-secondary)]">
        <span>
          Identity:{' '}
          {result.identity_preserved == null
            ? <span>—</span>
            : result.identity_preserved
              ? <span className="text-green-400">✓ preserved</span>
              : <span className="text-red-400">✗ changed</span>}
        </span>
        {scoreDelta != null && (
          <span>
            Score: {result.before_score?.toFixed(2)} →{' '}
            {result.after_score?.toFixed(2)}{' '}
            <span className={scoreDelta >= 0 ? 'text-green-400' : 'text-red-400'}>
              ({scoreDelta >= 0 ? '+' : ''}{scoreDelta.toFixed(2)})
            </span>
          </span>
        )}
        <span className="ml-auto">{result.operation} · {result.provider}</span>
      </div>

      <div className="flex border-t border-[var(--border)]">
        <button
          onClick={onReject}
          className="flex-1 flex items-center justify-center gap-1.5 py-2 text-sm text-red-400 hover:bg-red-950/30 transition-colors"
        >
          <X size={14} /> Reject <span className="text-xs opacity-50">[R]</span>
        </button>
        <div className="w-px bg-[var(--border)]" />
        <button
          onClick={onApprove}
          className="flex-1 flex items-center justify-center gap-1.5 py-2 text-sm text-green-400 hover:bg-green-950/30 transition-colors"
        >
          <Check size={14} /> Approve <span className="text-xs opacity-50">[A]</span>
        </button>
      </div>
    </div>
  )
}

// ── Tab 1: Outpaint / Fit ──────────────────────────────────────────────────────

function OutpaintTab() {
  const { activeProject } = useProjectStore()
  const { selectedIds } = useAssetStore()
  const { success, error: toastError } = useToast()
  const queryClient = useQueryClient()

  const [selectedRatio, setSelectedRatio] = useState<AspectRatio>('1:1')
  const [customW, setCustomW] = useState(1024)
  const [customH, setCustomH] = useState(1024)
  const [provider, setProvider] = useState('auto')
  const [autoDetect, setAutoDetect] = useState(true)
  const [preserveIdentity, setPreserveIdentity] = useState(true)
  const [prompt, setPrompt] = useState('')

  const runMutation = useMutation({
    mutationFn: () => {
      const ratio = ASPECT_OPTIONS.find(a => a.label === selectedRatio)!
      const w = selectedRatio === 'custom' ? customW : ratio.w
      const h = selectedRatio === 'custom' ? customH : ratio.h
      return augmentationApi.autoFit(
        activeProject!.id,
        Array.from(selectedIds),
        w,
        h,
        provider,
        prompt || undefined,
      )
    },
    onSuccess: data => {
      success(`Started auto-fit for ${data.asset_count} images (job ${data.job_id})`)
      queryClient.invalidateQueries({ queryKey: ['augmentation-pending', activeProject?.id] })
    },
    onError: () => toastError('Auto-fit failed'),
  })

  const targetW = selectedRatio === 'custom'
    ? customW
    : ASPECT_OPTIONS.find(a => a.label === selectedRatio)?.w ?? 1024
  const targetH = selectedRatio === 'custom'
    ? customH
    : ASPECT_OPTIONS.find(a => a.label === selectedRatio)?.h ?? 1024

  return (
    <div className="space-y-5 max-w-xl">
      {/* Aspect ratio */}
      <div>
        <label className="block text-xs font-medium text-[var(--text-secondary)] mb-2 uppercase tracking-wide">
          Target Aspect Ratio
        </label>
        <div className="flex flex-wrap gap-2">
          {ASPECT_OPTIONS.map(opt => (
            <button
              key={opt.label}
              onClick={() => setSelectedRatio(opt.label)}
              className={`btn btn-sm ${selectedRatio === opt.label ? 'bg-[var(--accent)] text-white' : 'btn-secondary'}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {selectedRatio === 'custom' && (
          <div className="flex gap-3 mt-3">
            <div className="flex-1">
              <label className="text-xs text-[var(--text-secondary)] mb-1 block">Width (px)</label>
              <input
                type="number"
                min={64}
                max={4096}
                value={customW}
                onChange={e => setCustomW(Number(e.target.value))}
                className="w-full bg-transparent border border-[var(--border)] rounded px-3 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
            <div className="flex-1">
              <label className="text-xs text-[var(--text-secondary)] mb-1 block">Height (px)</label>
              <input
                type="number"
                min={64}
                max={4096}
                value={customH}
                onChange={e => setCustomH(Number(e.target.value))}
                className="w-full bg-transparent border border-[var(--border)] rounded px-3 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          </div>
        )}
        <p className="text-xs text-[var(--text-secondary)] mt-1">
          Output: {targetW} × {targetH} px
        </p>
      </div>

      {/* Selected count */}
      <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
        <LayoutGrid size={14} />
        <span>
          {selectedIds.size > 0
            ? `Selected: ${selectedIds.size} image${selectedIds.size !== 1 ? 's' : ''}`
            : 'No images selected — all project images will be processed'}
        </span>
      </div>

      {/* Provider */}
      <div>
        <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1 uppercase tracking-wide">
          Provider
        </label>
        <select
          value={provider}
          onChange={e => setProvider(e.target.value)}
          className="w-full bg-transparent border border-[var(--border)] rounded px-3 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
        >
          {PROVIDER_OPTIONS.map(p => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </div>

      {/* Options */}
      <div className="space-y-2">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoDetect}
            onChange={e => setAutoDetect(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          <span className="text-sm text-[var(--text-primary)]">Auto-detect subject bounds</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={preserveIdentity}
            onChange={e => setPreserveIdentity(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          <span className="text-sm text-[var(--text-primary)]">Preserve identity during fill</span>
        </label>
      </div>

      {/* Prompt */}
      <div>
        <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1 uppercase tracking-wide">
          Optional Prompt
        </label>
        <input
          type="text"
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          placeholder="e.g. outdoor park, soft natural lighting"
          className="w-full bg-transparent border border-[var(--border)] rounded px-3 py-1.5 text-sm text-[var(--text-primary)] placeholder-[var(--text-secondary)]/50 focus:outline-none focus:border-[var(--accent)]"
        />
      </div>

      {/* Actions */}
      <div className="flex gap-3 items-center">
        <button
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending || !activeProject}
          className="btn btn-primary flex items-center gap-1.5"
        >
          {runMutation.isPending
            ? <RefreshCw size={14} className="animate-spin" />
            : <Wand2 size={14} />}
          Run All
        </button>

        {runMutation.isPending && (
          <span className="text-xs text-[var(--text-secondary)]">Processing...</span>
        )}
      </div>
      <p className="text-xs text-[var(--text-secondary)]">
        Augmentation runs non-destructively. Generated results land in Review Results for approval before they affect your dataset.
      </p>
    </div>
  )
}

// ── Tab 2: Expansion Plan ──────────────────────────────────────────────────────

function ExpansionPlanTab() {
  const { activeProject } = useProjectStore()
  const { success, error: toastError } = useToast()
  const queryClient = useQueryClient()
  const [skipped, setSkipped] = useState<Set<string>>(new Set())
  const [executingId, setExecutingId] = useState<string | null>(null)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['augmentation-plan', activeProject?.id],
    queryFn: () => augmentationApi.getPlan(activeProject!.id),
    enabled: !!activeProject?.id,
  })

  const plans = (data?.plans ?? []).filter(p => !skipped.has(p.id))

  const executeMutation = useMutation({
    mutationFn: (plan: AugmentationPlan) => {
      if (!plan.source_asset_id) throw new Error('No source asset')
      const w = (plan.params?.target_width as number | undefined) ?? 1024
      const h = (plan.params?.target_height as number | undefined) ?? 1024
      return augmentationApi.outpaint(plan.source_asset_id, w, h)
    },
    onSuccess: () => {
      success('Operation started — check Review Results tab')
      queryClient.invalidateQueries({ queryKey: ['augmentation-pending', activeProject?.id] })
      setExecutingId(null)
    },
    onError: () => {
      toastError('Operation failed')
      setExecutingId(null)
    },
  })

  const executeAllMutation = useMutation({
    mutationFn: async () => {
      for (const plan of plans) {
        if (!plan.source_asset_id) continue
        const w = (plan.params?.target_width as number | undefined) ?? 1024
        const h = (plan.params?.target_height as number | undefined) ?? 1024
        await augmentationApi.outpaint(plan.source_asset_id, w, h)
      }
    },
    onSuccess: () => {
      success('All operations started')
      queryClient.invalidateQueries({ queryKey: ['augmentation-pending', activeProject?.id] })
    },
    onError: () => toastError('Some operations failed'),
  })

  if (!activeProject) {
    return <p className="text-[var(--text-secondary)] py-8 text-center">Select a project.</p>
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-[var(--text-secondary)]">
          {plans.length} operation{plans.length !== 1 ? 's' : ''} recommended
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => refetch()}
            className="btn btn-sm btn-secondary flex items-center gap-1"
          >
            <RefreshCw size={12} /> Refresh
          </button>
          {plans.length > 0 && (
            <button
              onClick={() => executeAllMutation.mutate()}
              disabled={executeAllMutation.isPending}
              className="btn btn-sm btn-primary flex items-center gap-1"
            >
              {executeAllMutation.isPending
                ? <RefreshCw size={12} className="animate-spin" />
                : <Play size={12} />}
              Execute All
            </button>
          )}
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-8 justify-center text-[var(--text-secondary)]">
          <RefreshCw size={16} className="animate-spin" /> Loading plan...
        </div>
      )}

      {!isLoading && plans.length === 0 && (
        <div className="text-center py-12 text-[var(--text-secondary)]">
          <Wand2 size={32} className="mx-auto mb-3 opacity-40" />
          <p>No augmentation plans available.</p>
          <p className="text-xs mt-1">Run the Dataset Coach for recommendations.</p>
        </div>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {plans.map(plan => (
          <PlanItem
            key={plan.id}
            plan={plan}
            isExecuting={executingId === plan.id && executeMutation.isPending}
            onExecute={() => {
              setExecutingId(plan.id)
              executeMutation.mutate(plan)
            }}
            onSkip={() => setSkipped(s => new Set([...s, plan.id]))}
          />
        ))}
      </div>
    </div>
  )
}

// ── Tab 3: Review Results ──────────────────────────────────────────────────────

function ReviewResultsTab() {
  const { success, error: toastError } = useToast()
  const queryClient = useQueryClient()
  const [focusedIndex, setFocusedIndex] = useState(0)

  const { activeProject } = useProjectStore()
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['augmentation-pending', activeProject?.id],
    queryFn: () => augmentationApi.listPending(activeProject?.id),
    refetchInterval: 10_000,
    enabled: !!activeProject?.id,
  })

  const results = (data?.results ?? []).filter(r => r.status === 'pending_review')

  const approveMutation = useMutation({
    mutationFn: (id: string) => augmentationApi.approveResult(id),
    onSuccess: () => {
      success('Result approved')
      queryClient.invalidateQueries({ queryKey: ['augmentation-pending', activeProject?.id] })
      queryClient.invalidateQueries({ queryKey: ['assets'] })
      queryClient.invalidateQueries({ queryKey: ['project-stats'] })
    },
    onError: () => toastError('Approve failed'),
  })

  const rejectMutation = useMutation({
    mutationFn: (id: string) => augmentationApi.rejectResult(id),
    onSuccess: () => {
      success('Result rejected')
      queryClient.invalidateQueries({ queryKey: ['augmentation-pending', activeProject?.id] })
      queryClient.invalidateQueries({ queryKey: ['assets'] })
      queryClient.invalidateQueries({ queryKey: ['project-stats'] })
    },
    onError: () => toastError('Reject failed'),
  })

  const handleApprove = useCallback((id: string) => {
    approveMutation.mutate(id)
  }, [approveMutation])

  const handleReject = useCallback((id: string) => {
    rejectMutation.mutate(id)
  }, [rejectMutation])

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-[var(--text-secondary)]">
          {results.length} result{results.length !== 1 ? 's' : ''} awaiting review
        </p>
        <button
          onClick={() => refetch()}
          className="btn btn-sm btn-secondary flex items-center gap-1"
        >
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-8 justify-center text-[var(--text-secondary)]">
          <RefreshCw size={16} className="animate-spin" /> Loading results...
        </div>
      )}

      {!isLoading && results.length === 0 && (
        <div className="text-center py-16 text-[var(--text-secondary)]">
          <Check size={36} className="mx-auto mb-3 opacity-40" />
          <p className="font-medium">No results awaiting review</p>
          <p className="text-xs mt-1">Augmented images will appear here for approval.</p>
        </div>
      )}

      {results.length > 0 && (
        <p className="text-xs text-[var(--text-secondary)] mb-3">
          Tip: click a card to focus it, then press{' '}
          <kbd className="bg-[var(--border)] px-1 rounded">A</kbd> to approve or{' '}
          <kbd className="bg-[var(--border)] px-1 rounded">R</kbd> to reject.
        </p>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {results.map((result, i) => (
          <div
            key={result.id}
            onClick={() => setFocusedIndex(i)}
            className="cursor-pointer"
          >
            <ResultCard
              result={result}
              focused={focusedIndex === i}
              onApprove={() => handleApprove(result.id)}
              onReject={() => handleReject(result.id)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function Augmentation() {
  const [activeTab, setActiveTab] = useState<TabName>('Outpaint / Fit')

  return (
    <div className="p-6 overflow-y-auto h-full">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Augmentation</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Expand, fit, and diversify your dataset with AI-powered augmentation
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--border)] mb-6">
        {TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-[var(--accent)] text-[var(--accent)]'
                : 'border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'Outpaint / Fit' && <OutpaintTab />}
      {activeTab === 'Expansion Plan' && <ExpansionPlanTab />}
      {activeTab === 'Review Results' && <ReviewResultsTab />}
    </div>
  )
}
