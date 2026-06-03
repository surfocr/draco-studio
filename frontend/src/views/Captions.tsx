import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Brain,
  RefreshCw,
  Check,
  X,
  ChevronDown,
  ChevronUp,
  Zap,
  GitCompare,
  Save,
  RotateCcw,
  Download,
  BarChart2,
  AlignLeft,
  Search,
  AlertTriangle,
  Clock,
  Hash,
  FileText,
} from 'lucide-react'
import { clsx } from 'clsx'
import { assetsApi, captionsApi, projectsApi } from '@/hooks/useApi'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useProjectStore } from '@/stores/useProjectStore'
import { useToast } from '@/components/providers/ToastProvider'
import type { AssetSummary, CaptionStyle, CaptionVersion, CaptionConsistencyReport } from '@/types/api'

// ── Constants ─────────────────────────────────────────────────────────────────

const CAPTION_STYLES: Array<{ value: CaptionStyle; label: string }> = [
  { value: 'natural', label: 'Natural' },
  { value: 'concise', label: 'Concise' },
  { value: 'danbooru_tags', label: 'Danbooru' },
  { value: 'wd_tags', label: 'WD' },
  { value: 'training_literal', label: 'Training' },
]

const PROVIDERS = ['ollama', 'gemini', 'openai', 'florence2']

type FilterTab = 'all' | 'captioned' | 'uncaptioned' | 'needs-review'
type SortMode = 'score' | 'imported_at' | 'caption_length'
type TargetModel = 'flux_1' | 'flux_2' | 'z_image' | 'wan_2_2' | 'sdxl' | 'pony'

const TARGET_MODELS: Array<{ value: TargetModel; label: string; defaultStyle: CaptionStyle; recommendedTagger: string; exportFormat: string }> = [
  { value: 'flux_1', label: 'Flux.1', defaultStyle: 'natural', recommendedTagger: 'JoyCaption', exportFormat: 'ai-toolkit' },
  { value: 'flux_2', label: 'Flux.2', defaultStyle: 'natural', recommendedTagger: 'JoyCaption', exportFormat: 'ai-toolkit' },
  { value: 'z_image', label: 'Z-Image', defaultStyle: 'natural', recommendedTagger: 'JoyCaption', exportFormat: 'ai-toolkit' },
  { value: 'wan_2_2', label: 'WAN 2.2', defaultStyle: 'natural', recommendedTagger: 'Qwen2.5-VL-7B', exportFormat: 'musubi-tuner' },
  { value: 'sdxl', label: 'SDXL', defaultStyle: 'wd_tags', recommendedTagger: 'WD-EVA02-Large-Tagger-v3', exportFormat: 'kohya_ss' },
  { value: 'pony', label: 'Pony', defaultStyle: 'wd_tags', recommendedTagger: 'WD-EVA02-Large-Tagger-v3', exportFormat: 'kohya_ss' },
]

function targetMeta(targetModel: TargetModel) {
  return TARGET_MODELS.find((item) => item.value === targetModel) ?? TARGET_MODELS[0]
}

// ── Helper: count tokens (rough estimate) ─────────────────────────────────────

function countTokens(text: string): number {
  return Math.ceil(text.length / 4)
}

function countWords(text: string): number {
  return text.trim() === '' ? 0 : text.trim().split(/\s+/).length
}

// ── Helper: highlight trigger word occurrences ────────────────────────────────

function highlightTriggerWord(text: string, triggerWord: string): React.ReactNode {
  if (!triggerWord || !text) return text
  const escaped = triggerWord.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return parts.map((part, i) =>
    part.toLowerCase() === triggerWord.toLowerCase() ? (
      <mark
        key={i}
        className="bg-yellow-400/30 text-yellow-200 rounded px-0.5"
      >
        {part}
      </mark>
    ) : (
      part
    )
  )
}

// ── Provider badge color ──────────────────────────────────────────────────────

function providerBadgeClass(provider: string): string {
  switch (provider) {
    case 'ollama':    return 'bg-emerald-900/40 text-emerald-400 border border-emerald-700/40'
    case 'gemini':    return 'bg-blue-900/40 text-blue-400 border border-blue-700/40'
    case 'openai':    return 'bg-violet-900/40 text-violet-400 border border-violet-700/40'
    case 'florence2': return 'bg-orange-900/40 text-orange-400 border border-orange-700/40'
    case 'human':     return 'bg-pink-900/40 text-pink-400 border border-pink-700/40'
    default:          return 'bg-surface-elevated text-text-secondary border border-border'
  }
}

// ── Left Panel: Asset Row ─────────────────────────────────────────────────────

interface AssetRowProps {
  asset: AssetSummary
  isSelected: boolean
  isActive: boolean
  isChecked: boolean
  onSelect: (id: string) => void
  onCheck: (id: string, checked: boolean) => void
}

function AssetRow({ asset, isSelected, isActive, isChecked, onSelect, onCheck }: AssetRowProps) {
  const thumbnailUrl = assetsApi.thumbnailUrl(asset.id, 128)
  const hasCaptionId = !!asset.active_caption_id

  return (
    <div
      className={clsx(
        'flex items-center gap-2 px-2 py-1.5 cursor-pointer transition-colors border-b border-border last:border-0 group',
        isActive
          ? 'bg-accent/15 border-l-2 border-l-accent'
          : 'hover:bg-surface-elevated border-l-2 border-l-transparent'
      )}
      onClick={() => onSelect(asset.id)}
    >
      <input
        type="checkbox"
        checked={isChecked}
        onChange={(e) => { e.stopPropagation(); onCheck(asset.id, e.target.checked) }}
        onClick={(e) => e.stopPropagation()}
        className="flex-shrink-0 accent-accent"
      />
      <img
        src={thumbnailUrl}
        alt={asset.filename}
        className="w-12 h-12 object-cover rounded flex-shrink-0 bg-surface-elevated"
        loading="lazy"
      />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-text-primary truncate leading-tight">{asset.filename}</p>
        {hasCaptionId ? (
          <p className="text-[10px] text-text-secondary truncate mt-0.5 leading-tight italic">
            {isSelected ? '' : 'Has caption'}
          </p>
        ) : (
          <span className="inline-block text-[9px] px-1.5 py-0.5 rounded bg-orange-900/40 text-orange-400 border border-orange-700/40 mt-0.5">
            No caption
          </span>
        )}
      </div>
    </div>
  )
}

// ── Version History Item ──────────────────────────────────────────────────────

interface VersionItemProps {
  version: CaptionVersion
  onActivate: (id: string) => void
  isActivating: boolean
}

function VersionItem({ version, onActivate, isActivating }: VersionItemProps) {
  const date = new Date(version.created_at).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
  return (
    <div
      className={clsx(
        'flex items-start gap-2 px-3 py-2 border-b border-border last:border-0 text-xs',
        version.is_active ? 'bg-accent/10' : 'hover:bg-surface-elevated'
      )}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
          <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-medium', providerBadgeClass(version.provider))}>
            {version.provider}
          </span>
          <span className="text-[9px] text-text-secondary">{version.style}</span>
          {version.is_active && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-accent/20 text-accent border border-accent/40">
              active
            </span>
          )}
          {version.is_edited && (
            <span className="px-1.5 py-0.5 rounded text-[9px] bg-yellow-900/30 text-yellow-400 border border-yellow-700/40">
              edited
            </span>
          )}
          {version.latency_ms != null && (
            <span className="text-[9px] text-text-secondary flex items-center gap-0.5">
              <Clock size={8} />{version.latency_ms}ms
            </span>
          )}
        </div>
        <p className="text-text-secondary truncate">{version.text.slice(0, 80)}{version.text.length > 80 ? '…' : ''}</p>
        <p className="text-[9px] text-text-secondary/60 mt-0.5">{date}</p>
      </div>
      {!version.is_active && (
        <button
          className="btn btn-sm btn-ghost flex-shrink-0 text-[10px] px-2 py-0.5"
          onClick={() => onActivate(version.id)}
          disabled={isActivating}
        >
          Use
        </button>
      )}
    </div>
  )
}

// ── Compare Panel Result ──────────────────────────────────────────────────────

interface CompareResultProps {
  version: CaptionVersion
  onUse: (version: CaptionVersion) => void
}

function CompareResult({ version, onUse }: CompareResultProps) {
  return (
    <div className="border border-border rounded-lg p-3 bg-surface-elevated space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-medium', providerBadgeClass(version.provider))}>
            {version.provider}
          </span>
          {version.latency_ms != null && (
            <span className="text-[10px] text-text-secondary flex items-center gap-0.5">
              <Clock size={9} />{version.latency_ms}ms
            </span>
          )}
        </div>
        <button
          className="btn btn-sm btn-primary text-[10px] px-2 py-0.5"
          onClick={() => onUse(version)}
        >
          Use This
        </button>
      </div>
      <p className="text-xs text-text-primary leading-relaxed">{version.text}</p>
      <div className="flex gap-2 text-[10px] text-text-secondary">
        <span>{version.text.length} chars</span>
        <span>{countWords(version.text)} words</span>
        <span>~{countTokens(version.text)} tokens</span>
      </div>
    </div>
  )
}

// ── Consistency Modal ─────────────────────────────────────────────────────────

interface ConsistencyModalProps {
  report: CaptionConsistencyReport
  onClose: () => void
}

function ConsistencyModal({ report, onClose }: ConsistencyModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-surface border border-border rounded-xl shadow-2xl w-[600px] max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <BarChart2 size={16} className="text-accent" />
            <h2 className="text-sm font-semibold text-text-primary">Caption Consistency Analysis</h2>
          </div>
          <button className="btn-ghost btn-icon" onClick={onClose}><X size={16} /></button>
        </div>
        {/* Body */}
        <div className="overflow-y-auto flex-1 p-5 space-y-5">
          {/* Stats row */}
          <div className="grid grid-cols-3 gap-3">
            <div className="card p-3 text-center">
              <p className="text-2xl font-bold text-text-primary">{report.total_captioned}</p>
              <p className="text-[11px] text-text-secondary mt-0.5">Captioned</p>
            </div>
            <div className="card p-3 text-center">
              <p className="text-2xl font-bold text-orange-400">{report.total_uncaptioned}</p>
              <p className="text-[11px] text-text-secondary mt-0.5">Uncaptioned</p>
            </div>
            <div className="card p-3 text-center">
              <p className="text-2xl font-bold text-text-primary">{report.avg_length.toFixed(0)}</p>
              <p className="text-[11px] text-text-secondary mt-0.5">Avg Length</p>
            </div>
          </div>

          {/* Top words */}
          {report.common_words.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-text-primary mb-2 flex items-center gap-1.5">
                <Hash size={12} /> Top 10 Common Words
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {report.common_words.slice(0, 10).map((w) => (
                  <span
                    key={w.word}
                    className="px-2 py-0.5 rounded-full bg-surface-elevated border border-border text-xs text-text-secondary"
                  >
                    {w.word}
                    <span className="ml-1 text-text-secondary/60 text-[10px]">×{w.count}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Inconsistent formatting */}
          {report.inconsistent_formatting.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-text-primary mb-2 flex items-center gap-1.5">
                <AlertTriangle size={12} className="text-yellow-400" /> Formatting Issues
              </h3>
              <div className="space-y-1">
                {report.inconsistent_formatting.map((item, i) => (
                  <p key={i} className="text-xs text-text-secondary bg-yellow-900/10 border border-yellow-700/30 rounded px-2 py-1">
                    {item}
                  </p>
                ))}
              </div>
            </div>
          )}

          {/* Recommendations */}
          {report.recommendations.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-text-primary mb-2 flex items-center gap-1.5">
                <AlertTriangle size={12} className="text-yellow-400" /> Recommendations
              </h3>
              <div className="space-y-2">
                {report.recommendations.map((rec, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 bg-yellow-900/15 border border-yellow-700/30 rounded-lg px-3 py-2 text-xs text-yellow-200"
                  >
                    <AlertTriangle size={12} className="text-yellow-400 flex-shrink-0 mt-0.5" />
                    <span>{rec}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t border-border shrink-0 flex justify-end">
          <button className="btn btn-secondary btn-sm" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  )
}

// ── Find & Replace Inline Form ────────────────────────────────────────────────

interface FindReplaceFormProps {
  onApply: (find: string, replace: string) => void
  onClose: () => void
  isPending: boolean
}

function FindReplaceForm({ onApply, onClose, isPending }: FindReplaceFormProps) {
  const [find, setFind] = useState('')
  const [replace, setReplace] = useState('')
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-text-secondary font-medium">Find:</span>
      <input
        value={find}
        onChange={(e) => setFind(e.target.value)}
        className="text-xs px-2 py-1 rounded border border-border bg-surface-elevated text-text-primary w-32 focus:outline-none focus:border-accent"
        placeholder="search text"
      />
      <span className="text-xs text-text-secondary font-medium">Replace:</span>
      <input
        value={replace}
        onChange={(e) => setReplace(e.target.value)}
        className="text-xs px-2 py-1 rounded border border-border bg-surface-elevated text-text-primary w-32 focus:outline-none focus:border-accent"
        placeholder="replacement"
      />
      <button
        className="btn btn-sm btn-primary"
        onClick={() => onApply(find, replace)}
        disabled={isPending || !find}
      >
        {isPending ? <RefreshCw size={10} className="animate-spin" /> : <Check size={10} />}
        Apply
      </button>
      <button className="btn btn-sm btn-ghost" onClick={onClose}><X size={10} /></button>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export function Captions() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const activeProject = useProjectStore((s) => s.activeProject)

  // Left panel state
  const [filterTab, setFilterTab] = useState<FilterTab>('all')
  const [sortMode, setSortMode] = useState<SortMode>('imported_at')
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())
  const [activeAssetId, setActiveAssetId] = useState<string | null>(null)

  // Center panel state
  const [activeStyle, setActiveStyle] = useState<CaptionStyle>('natural')
  const [selectedProvider, setSelectedProvider] = useState('ollama')
  const [targetModel, setTargetModel] = useState<TargetModel>('flux_1')
  const [characterMode, setCharacterMode] = useState(false)
  const [editText, setEditText] = useState('')
  const [isDirty, setIsDirty] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)

  // Right panel state
  const [compareResults, setCompareResults] = useState<CaptionVersion[] | null>(null)

  // Bottom toolbar state
  const [prependText, setPrependText] = useState('')
  const [appendText, setAppendText] = useState('')
  const [showFindReplace, setShowFindReplace] = useState(false)

  // Modals
  const [consistencyReport, setConsistencyReport] = useState<CaptionConsistencyReport | null>(null)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const assetListRef = useRef<HTMLDivElement>(null)

  // ── Data fetching ──────────────────────────────────────────────────────────

  const hasCaption = filterTab === 'captioned' ? true : filterTab === 'uncaptioned' ? false : undefined
  const isNeedsReview = filterTab === 'needs-review'

  const sortByField = sortMode === 'score' ? 'composite_score' : 'imported_at'

  const { data: assetsData, isLoading: assetsLoading } = useQuery({
    queryKey: ['caption-assets', activeProject?.id, filterTab, sortMode],
    queryFn: () =>
      assetsApi.list(activeProject!.id, {
        page: 1,
        page_size: 200,
        sort_by: sortByField as 'composite_score' | 'imported_at',
        sort_dir: sortMode === 'score' ? 'desc' : 'desc',
        has_caption: isNeedsReview ? true : hasCaption,
      }),
    enabled: !!activeProject?.id,
  })

  const assets: AssetSummary[] = useMemo(() => {
    const items = assetsData?.items ?? []
    if (sortMode === 'caption_length') {
      return [...items].sort((_a, _b) => {
        // We don't have caption text here; just fallback to import order
        return 0
      })
    }
    return items
  }, [assetsData, sortMode])

  const assetVirtualizer = useVirtualizer({
    count: assets.length,
    getScrollElement: () => assetListRef.current,
    estimateSize: () => 56,
    overscan: 5,
  })

  const activeAsset = assets.find((a) => a.id === activeAssetId) ?? null

  // Auto-select first asset
  useEffect(() => {
    if (!activeAssetId && assets.length > 0) {
      setActiveAssetId(assets[0].id)
    }
  }, [assets, activeAssetId])

  // Fetch captions for active asset
  const { data: captions = [], isLoading: captionsLoading } = useQuery({
    queryKey: ['captions', activeAssetId],
    queryFn: () => captionsApi.list(activeAssetId!),
    enabled: !!activeAssetId,
  })

  const activeCaption = captions.find((c) => c.is_active) ?? captions[0] ?? null
  const { data: runtimeConfig } = useQuery({
    queryKey: ['project-runtime', activeProject?.id],
    queryFn: () => projectsApi.getRuntime(activeProject!.id),
    enabled: !!activeProject?.id,
    staleTime: 30_000,
  })

  const runtimeUpdateMutation = useMutation({
    mutationFn: (
      patch: {
        task_provider_options: Record<string, Record<string, unknown>>
      }
    ) => projectsApi.updateRuntime(activeProject!.id, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-runtime', activeProject?.id] })
    },
  })

  // Sync textarea when active caption changes (and not dirty)
  useEffect(() => {
    if (!isDirty) {
      setEditText(activeCaption?.text ?? '')
    }
  }, [activeCaption?.id, isDirty]) // eslint-disable-line react-hooks/exhaustive-deps

  // Reset dirty on asset change
  useEffect(() => {
    setIsDirty(false)
    setEditText(activeCaption?.text ?? '')
    setCompareResults(null)
  }, [activeAssetId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const runtimeOptions = runtimeConfig?.task_provider_options?.caption as Record<string, unknown> | undefined
    const runtimeTarget = String(runtimeOptions?.target_model ?? 'flux_1') as TargetModel
    const runtimeCharacterMode = Boolean(runtimeOptions?.character_mode)
    setTargetModel(runtimeTarget)
    setCharacterMode(runtimeCharacterMode)
  }, [runtimeConfig?.task_provider_options])

  // ── Mutations ─────────────────────────────────────────────────────────────

  const generateMutation = useMutation({
    mutationFn: () => captionsApi.generate(activeAssetId!, selectedProvider, activeStyle, {
      target_model: targetModel,
      character_mode: characterMode,
    }),
    onSuccess: (newVersion) => {
      queryClient.invalidateQueries({ queryKey: ['captions', activeAssetId] })
      queryClient.invalidateQueries({ queryKey: ['caption-assets'] })
      toast.success(`Caption generated by ${newVersion.provider}`)
    },
    onError: () => toast.error('Caption generation failed'),
  })

  const compareMutation = useMutation({
    mutationFn: () => captionsApi.compare(activeAssetId!, PROVIDERS, activeStyle, {
      target_model: targetModel,
      character_mode: characterMode,
    }),
    onSuccess: (results) => {
      setCompareResults(results)
    },
    onError: () => toast.error('Compare failed'),
  })

  const activateMutation = useMutation({
    mutationFn: (versionId: string) => captionsApi.activate(versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['captions', activeAssetId] })
      queryClient.invalidateQueries({ queryKey: ['caption-assets'] })
    },
    onError: () => toast.error('Failed to activate version'),
  })

  const editMutation = useMutation({
    mutationFn: (text: string) => captionsApi.edit(activeCaption!.id, text, 'human'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['captions', activeAssetId] })
      queryClient.invalidateQueries({ queryKey: ['caption-assets'] })
      setIsDirty(false)
      toast.success('Caption saved')
    },
    onError: () => toast.error('Failed to save caption'),
  })

  const bulkGenerateMutation = useMutation({
    mutationFn: (assetIds: string[]) =>
      captionsApi.bulkGenerate(activeProject!.id, assetIds, selectedProvider, activeStyle, {
        target_model: targetModel,
        character_mode: characterMode,
      }),
    onSuccess: (result) => {
      toast.success(`Queued caption generation for ${result.asset_count} assets`)
      queryClient.invalidateQueries({ queryKey: ['caption-assets'] })
    },
    onError: () => toast.error('Bulk generation failed'),
  })

  const bulkEditMutation = useMutation({
    mutationFn: (args: { op: 'prepend' | 'append' | 'find_replace' | 'normalize'; opts: Record<string, string> }) =>
      captionsApi.bulkEdit(activeProject!.id, checkedIds.size > 0 ? [...checkedIds] : assets.map((a) => a.id), args.op, args.opts),
    onSuccess: (result) => {
      toast.success(`${result.operation}: modified ${result.modified} captions`)
      queryClient.invalidateQueries({ queryKey: ['captions', activeAssetId] })
      queryClient.invalidateQueries({ queryKey: ['caption-assets'] })
    },
    onError: () => toast.error('Bulk edit failed'),
  })

  const exportMutation = useMutation({
    mutationFn: () =>
      captionsApi.exportSidecars(activeProject!.id, checkedIds.size > 0 ? [...checkedIds] : undefined),
    onSuccess: (result) => {
      toast.success(`Exporting ${result.asset_count} caption sidecars…`)
    },
    onError: () => toast.error('Export failed'),
  })

  const consistencyMutation = useMutation({
    mutationFn: () =>
      captionsApi.consistency(activeProject!.id, activeProject?.trigger_word ?? undefined),
    onSuccess: (report) => {
      setConsistencyReport(report)
    },
    onError: () => toast.error('Consistency analysis failed'),
  })

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleSelectAsset = useCallback((id: string) => {
    setActiveAssetId(id)
  }, [])

  const handleCheck = useCallback((id: string, checked: boolean) => {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id); else next.delete(id)
      return next
    })
  }, [])

  const handleCheckAll = useCallback((checked: boolean) => {
    setCheckedIds(checked ? new Set(assets.map((a) => a.id)) : new Set())
  }, [assets])

  const handleTextareaChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setEditText(e.target.value)
    setIsDirty(true)
  }, [])

  const handleSaveEdit = useCallback(() => {
    if (!activeCaption) return
    editMutation.mutate(editText)
  }, [activeCaption, editMutation, editText])

  const handleUseCompareResult = useCallback((version: CaptionVersion) => {
    activateMutation.mutate(version.id)
    setCompareResults(null)
    toast.success(`Using ${version.provider} caption`)
  }, [activateMutation, toast])

  const handleBulkGenerate = useCallback(() => {
    const targetIds =
      checkedIds.size > 0
        ? [...checkedIds]
        : assets.filter((a) => !a.active_caption_id).map((a) => a.id)
    if (targetIds.length === 0) {
      toast.error('No uncaptioned assets to generate')
      return
    }
    bulkGenerateMutation.mutate(targetIds)
  }, [checkedIds, assets, bulkGenerateMutation, toast])

  const handlePrepend = useCallback(() => {
    if (!prependText.trim()) return
    bulkEditMutation.mutate({ op: 'prepend', opts: { text: prependText } })
  }, [prependText, bulkEditMutation])

  const handleAppend = useCallback(() => {
    if (!appendText.trim()) return
    bulkEditMutation.mutate({ op: 'append', opts: { text: appendText } })
  }, [appendText, bulkEditMutation])

  const handleNormalize = useCallback(() => {
    bulkEditMutation.mutate({ op: 'normalize', opts: {} })
  }, [bulkEditMutation])

  const handleFindReplace = useCallback((find: string, replace: string) => {
    bulkEditMutation.mutate({ op: 'find_replace', opts: { find, replace } })
    setShowFindReplace(false)
  }, [bulkEditMutation])

  const saveCaptionRuntimeOptions = useCallback(
    (patch: Record<string, unknown>) => {
      if (!runtimeConfig) return
      runtimeUpdateMutation.mutate({
        task_provider_options: {
          ...runtimeConfig.task_provider_options,
          caption: {
            ...(runtimeConfig.task_provider_options.caption ?? {}),
            ...patch,
          },
        },
      })
    },
    [runtimeConfig, runtimeUpdateMutation]
  )

  const handleTargetModelChange = useCallback((nextModel: TargetModel) => {
    setTargetModel(nextModel)
    const nextMeta = targetMeta(nextModel)
    setActiveStyle(nextMeta.defaultStyle)
    saveCaptionRuntimeOptions({ target_model: nextModel })
  }, [saveCaptionRuntimeOptions])

  const handleCharacterModeChange = useCallback((nextValue: boolean) => {
    setCharacterMode(nextValue)
    saveCaptionRuntimeOptions({ character_mode: nextValue })
  }, [saveCaptionRuntimeOptions])

  // ── Guard: no active project ──────────────────────────────────────────────

  if (!activeProject) {
    return (
      <div className="flex items-center justify-center h-full text-text-secondary text-sm">
        Select a project to manage captions
      </div>
    )
  }

  const allChecked = assets.length > 0 && checkedIds.size === assets.length
  const someChecked = checkedIds.size > 0 && checkedIds.size < assets.length
  const isGenerating = generateMutation.isPending
  const thumbnailUrl = activeAsset ? assetsApi.thumbnailUrl(activeAsset.id, 512) : null
  const triggerWord = activeProject.trigger_word ?? ''
  const selectedTargetMeta = targetMeta(targetModel)

  // Caption stats
  const chars = editText.length
  const words = countWords(editText)
  const tokens = countTokens(editText)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Three-panel layout */}
      <div className="flex flex-1 min-h-0">

        {/* ── LEFT PANEL ─────────────────────────────────────────────────── */}
        <div className="w-[280px] flex-shrink-0 flex flex-col border-r border-border bg-surface">
          {/* Filter tabs header */}
          <div className="border-b border-border shrink-0">
            <div className="flex items-center gap-1 px-2 pt-2">
              {([
                { key: 'all', label: 'All' },
                { key: 'captioned', label: 'Captioned' },
                { key: 'uncaptioned', label: 'Uncaptioned' },
                { key: 'needs-review', label: 'Review' },
              ] as Array<{ key: FilterTab; label: string }>).map((tab) => (
                <button
                  key={tab.key}
                  className={clsx(
                    'text-[10px] px-2 py-1 rounded transition-colors',
                    filterTab === tab.key
                      ? 'bg-accent/20 text-accent font-medium'
                      : 'text-text-secondary hover:text-text-primary hover:bg-surface-elevated'
                  )}
                  onClick={() => setFilterTab(tab.key)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            {/* Sort + selected count row */}
            <div className="flex items-center gap-2 px-2 pb-2 pt-1">
              <select
                value={sortMode}
                onChange={(e) => setSortMode(e.target.value as SortMode)}
                className="text-[10px] py-0.5 px-1.5 flex-1 min-w-0"
              >
                <option value="imported_at">By Import Date</option>
                <option value="score">By Score</option>
                <option value="caption_length">By Caption Length</option>
              </select>
              {checkedIds.size > 0 && (
                <span className="badge badge-purple text-[9px] flex-shrink-0">
                  {checkedIds.size} sel
                </span>
              )}
            </div>
          </div>

          {/* Bulk-select header row */}
          <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border bg-surface-elevated shrink-0">
            <input
              type="checkbox"
              checked={allChecked}
              ref={(el) => { if (el) el.indeterminate = someChecked }}
              onChange={(e) => handleCheckAll(e.target.checked)}
              className="accent-accent"
            />
            <span className="text-[10px] text-text-secondary flex-1">
              {assetsLoading ? 'Loading…' : `${assets.length} assets`}
            </span>
            {assetsLoading && <RefreshCw size={10} className="animate-spin text-text-secondary" />}
          </div>

          {/* Asset list (virtualized) */}
          <div ref={assetListRef} className="flex-1 overflow-y-auto">
            {assetsLoading ? (
              <div className="p-3 space-y-2">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="flex gap-2 items-center">
                    <div className="skeleton h-4 w-4 rounded" />
                    <div className="skeleton h-12 w-12 rounded flex-shrink-0" />
                    <div className="flex-1 space-y-1.5">
                      <div className="skeleton h-3 w-3/4 rounded" />
                      <div className="skeleton h-2.5 w-1/2 rounded" />
                    </div>
                  </div>
                ))}
              </div>
            ) : assets.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-text-secondary p-4">
                <Brain size={28} className="opacity-20" />
                <p className="text-xs text-center">No assets match this filter</p>
              </div>
            ) : (
              <div style={{ height: assetVirtualizer.getTotalSize(), position: 'relative' }}>
                {assetVirtualizer.getVirtualItems().map((virtualRow) => {
                  const asset = assets[virtualRow.index]
                  return (
                    <div
                      key={asset.id}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: virtualRow.size,
                        transform: `translateY(${virtualRow.start}px)`,
                      }}
                    >
                      <AssetRow
                        asset={asset}
                        isSelected={checkedIds.has(asset.id)}
                        isActive={asset.id === activeAssetId}
                        isChecked={checkedIds.has(asset.id)}
                        onSelect={handleSelectAsset}
                        onCheck={handleCheck}
                      />
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* ── CENTER PANEL ───────────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {activeAsset ? (
            <>
              {/* Image preview */}
              <div className="relative shrink-0 bg-black/30 flex items-center justify-center" style={{ maxHeight: '256px', minHeight: '120px' }}>
                <img
                  src={thumbnailUrl!}
                  alt={activeAsset.filename}
                  className="max-h-64 max-w-full object-contain"
                />
                {isGenerating && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-sm">
                    <div className="flex items-center gap-2 text-white text-sm">
                      <RefreshCw size={18} className="animate-spin" />
                      <span>Generating caption…</span>
                    </div>
                  </div>
                )}
                {/* Filename overlay */}
                <div className="absolute bottom-0 left-0 right-0 px-3 py-1.5 bg-gradient-to-t from-black/70 to-transparent">
                  <p className="text-[11px] text-white/80 truncate">{activeAsset.filename}</p>
                </div>
              </div>

              {/* Target model + strategy */}
              <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2 shrink-0 bg-surface-elevated">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[10px] uppercase tracking-wide text-text-secondary">Target model</span>
                  <select
                    value={targetModel}
                    onChange={(e) => handleTargetModelChange(e.target.value as TargetModel)}
                    className="text-xs py-1 px-2"
                  >
                    {TARGET_MODELS.map((model) => (
                      <option key={model.value} value={model.value}>{model.label}</option>
                    ))}
                  </select>
                </div>
                <label className="flex items-center gap-1.5 text-[11px] text-text-secondary">
                  <input
                    type="checkbox"
                    checked={characterMode}
                    onChange={(e) => handleCharacterModeChange(e.target.checked)}
                    className="accent-accent"
                  />
                  Character mode
                </label>
              </div>

              <div className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0 bg-surface">
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-surface-elevated border border-border text-text-secondary">
                  Tagger: {selectedTargetMeta.recommendedTagger}
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-surface-elevated border border-border text-text-secondary">
                  Export: {selectedTargetMeta.exportFormat}
                </span>
              </div>

              {/* Style tabs */}
              <div className="flex items-center gap-0 border-b border-border px-3 shrink-0 bg-surface">
                {CAPTION_STYLES.map((s) => (
                  <button
                    key={s.value}
                    className={clsx(
                      'px-3 py-2 text-[11px] font-medium transition-colors border-b-2 -mb-px',
                      activeStyle === s.value
                        ? 'border-accent text-accent'
                        : 'border-transparent text-text-secondary hover:text-text-primary'
                    )}
                    onClick={() => setActiveStyle(s.value)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>

              {/* Caption editing area */}
              <div className="flex-1 overflow-y-auto flex flex-col min-h-0">
                <div className="p-3 flex flex-col gap-2 flex-1">
                  {captionsLoading ? (
                    <div className="skeleton h-24 rounded" />
                  ) : (
                    <>
                      {/* Textarea */}
                      <textarea
                        ref={textareaRef}
                        value={editText}
                        onChange={handleTextareaChange}
                        className="w-full resize-y text-sm text-text-primary bg-surface-elevated border border-border rounded-lg p-3 focus:outline-none focus:border-accent min-h-[80px] leading-relaxed"
                        placeholder="No caption yet. Generate one or type manually…"
                        rows={4}
                      />

                      {/* Stats row */}
                      <div className="flex items-center gap-3 text-[10px] text-text-secondary">
                        <span className="flex items-center gap-1"><FileText size={9} />{chars} chars</span>
                        <span className="flex items-center gap-1"><AlignLeft size={9} />{words} words</span>
                        <span className="flex items-center gap-1"><Hash size={9} />~{tokens} tokens</span>
                      </div>

                      {/* Trigger word highlight preview */}
                      {triggerWord && editText && (
                        <div className="bg-surface-elevated border border-border rounded-lg p-3 text-xs text-text-secondary leading-relaxed">
                          <p className="text-[9px] text-text-secondary/60 mb-1 uppercase tracking-wider">Preview with trigger word highlight</p>
                          <p>{highlightTriggerWord(editText, triggerWord)}</p>
                        </div>
                      )}

                      {/* Action row */}
                      <div className="flex items-center gap-2 flex-wrap">
                        <select
                          value={selectedProvider}
                          onChange={(e) => setSelectedProvider(e.target.value)}
                          className="text-xs py-1 px-2"
                          style={{ width: 'auto' }}
                        >
                          {PROVIDERS.map((p) => (
                            <option key={p} value={p}>{p}</option>
                          ))}
                        </select>

                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => generateMutation.mutate()}
                          disabled={isGenerating}
                        >
                          {isGenerating ? (
                            <RefreshCw size={11} className="animate-spin" />
                          ) : (
                            <Brain size={11} />
                          )}
                          Generate
                        </button>

                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => compareMutation.mutate()}
                          disabled={compareMutation.isPending}
                        >
                          {compareMutation.isPending ? (
                            <RefreshCw size={11} className="animate-spin" />
                          ) : (
                            <GitCompare size={11} />
                          )}
                          Compare Providers
                        </button>

                        {isDirty && (
                          <button
                            className="btn btn-sm"
                            style={{ background: 'rgba(34,197,94,0.15)', color: 'var(--success)', border: '1px solid rgba(34,197,94,0.3)' }}
                            onClick={handleSaveEdit}
                            disabled={editMutation.isPending}
                          >
                            {editMutation.isPending ? <RefreshCw size={10} className="animate-spin" /> : <Save size={10} />}
                            Save Edit
                          </button>
                        )}

                        {activeCaption && (
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => generateMutation.mutate()}
                            disabled={isGenerating}
                            title="Regenerate"
                          >
                            <RotateCcw size={11} />
                            Regenerate
                          </button>
                        )}
                      </div>

                      {/* Version history */}
                      {captions.length > 0 && (
                        <div className="border border-border rounded-lg overflow-hidden">
                          <button
                            className="w-full flex items-center justify-between px-3 py-2 text-xs text-text-secondary hover:bg-surface-elevated transition-colors"
                            onClick={() => setHistoryOpen((v) => !v)}
                          >
                            <span className="font-medium text-text-primary flex items-center gap-1.5">
                              <Clock size={11} />
                              Version History
                              <span className="badge text-[9px] ml-1">{captions.length}</span>
                            </span>
                            {historyOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                          </button>
                          {historyOpen && (
                            <div className="border-t border-border">
                              {captions.map((v) => (
                                <VersionItem
                                  key={v.id}
                                  version={v}
                                  onActivate={(id) => activateMutation.mutate(id)}
                                  isActivating={activateMutation.isPending}
                                />
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-text-secondary">
              <Brain size={40} className="opacity-20" />
              <p className="text-sm">Select an asset to edit captions</p>
            </div>
          )}
        </div>

        {/* ── RIGHT PANEL ────────────────────────────────────────────────── */}
        <div className="w-[300px] flex-shrink-0 flex flex-col border-l border-border bg-surface">
          {compareResults && compareResults.length > 0 ? (
            <>
              <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
                <span className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
                  <GitCompare size={12} />
                  Provider Comparison
                </span>
                <button
                  className="btn-ghost btn-icon"
                  onClick={() => setCompareResults(null)}
                >
                  <X size={14} />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto p-3 space-y-3">
                {compareResults.map((v) => (
                  <CompareResult
                    key={v.id}
                    version={v}
                    onUse={handleUseCompareResult}
                  />
                ))}
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-text-secondary p-4">
              <GitCompare size={32} className="opacity-20" />
              <p className="text-xs text-center text-text-secondary">
                Click <strong className="text-text-primary">Compare Providers</strong> to see results side by side
              </p>
              {compareMutation.isPending && (
                <div className="flex items-center gap-1.5 text-xs text-accent">
                  <RefreshCw size={12} className="animate-spin" />
                  <span>Comparing providers…</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── BOTTOM TOOLBAR ──────────────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border bg-surface px-3 py-2 flex flex-col gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Bulk Generate */}
          <button
            className="btn btn-primary btn-sm"
            onClick={handleBulkGenerate}
            disabled={bulkGenerateMutation.isPending}
          >
            {bulkGenerateMutation.isPending ? (
              <RefreshCw size={11} className="animate-spin" />
            ) : (
              <Brain size={11} />
            )}
            {checkedIds.size > 0 ? `Generate (${checkedIds.size})` : 'Bulk Generate'}
          </button>

          <div className="w-px h-5 bg-border" />

          {/* Prepend */}
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-text-secondary font-medium">Prepend:</span>
            <input
              value={prependText}
              onChange={(e) => setPrependText(e.target.value)}
              className="text-xs px-2 py-1 rounded border border-border bg-surface-elevated text-text-primary w-28 focus:outline-none focus:border-accent"
              placeholder="text to prepend"
            />
            <button
              className="btn btn-secondary btn-sm"
              onClick={handlePrepend}
              disabled={bulkEditMutation.isPending || !prependText.trim()}
            >
              <Check size={10} />
            </button>
          </div>

          {/* Append */}
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-text-secondary font-medium">Append:</span>
            <input
              value={appendText}
              onChange={(e) => setAppendText(e.target.value)}
              className="text-xs px-2 py-1 rounded border border-border bg-surface-elevated text-text-primary w-28 focus:outline-none focus:border-accent"
              placeholder="text to append"
            />
            <button
              className="btn btn-secondary btn-sm"
              onClick={handleAppend}
              disabled={bulkEditMutation.isPending || !appendText.trim()}
            >
              <Check size={10} />
            </button>
          </div>

          <div className="w-px h-5 bg-border" />

          {/* Find & Replace toggle */}
          <button
            className={clsx('btn btn-sm', showFindReplace ? 'btn-secondary' : 'btn-ghost')}
            onClick={() => setShowFindReplace((v) => !v)}
          >
            <Search size={11} />
            Find &amp; Replace
          </button>

          {/* Normalize */}
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleNormalize}
            disabled={bulkEditMutation.isPending}
          >
            <Zap size={11} />
            Normalize
          </button>

          <div className="flex-1" />

          {/* Export sidecars */}
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => exportMutation.mutate()}
            disabled={exportMutation.isPending}
          >
            {exportMutation.isPending ? <RefreshCw size={11} className="animate-spin" /> : <Download size={11} />}
            Export .txt Sidecars
          </button>

          {/* Consistency */}
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => consistencyMutation.mutate()}
            disabled={consistencyMutation.isPending}
          >
            {consistencyMutation.isPending ? (
              <RefreshCw size={11} className="animate-spin" />
            ) : (
              <BarChart2 size={11} />
            )}
            Consistency Analysis
          </button>
        </div>

        {/* Find & Replace inline form */}
        {showFindReplace && (
          <div className="py-1">
            <FindReplaceForm
              onApply={handleFindReplace}
              onClose={() => setShowFindReplace(false)}
              isPending={bulkEditMutation.isPending}
            />
          </div>
        )}
      </div>

      {/* ── CONSISTENCY MODAL ───────────────────────────────────────────────── */}
      {consistencyReport && (
        <ConsistencyModal
          report={consistencyReport}
          onClose={() => setConsistencyReport(null)}
        />
      )}
    </div>
  )
}
