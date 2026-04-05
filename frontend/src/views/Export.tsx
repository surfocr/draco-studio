import React, { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Download,
  Package,
  Settings,
  RefreshCw,
  CheckCircle,
  AlertTriangle,
  ExternalLink,
} from 'lucide-react'
import { exportApi } from '@/hooks/useApi'
import { useProjectStore } from '@/stores/useProjectStore'
import { useAssetStore } from '@/stores/useAssetStore'
import { useToast } from '@/components/providers/ToastProvider'
import type { ExportJob, ExportValidation } from '@/types/api'

// ── Helpers ────────────────────────────────────────────────────────────────────

const TABS = ['LoRA Dataset', 'Kohya SS', 'SimpleTuner', 'ZIP Archive', 'Custom'] as const
type TabName = typeof TABS[number]

// ── Progress Modal ─────────────────────────────────────────────────────────────

function ProgressModal({
  exportJobId,
  onClose,
}: {
  exportJobId: string
  onClose: () => void
}) {
  const [job, setJob] = useState<ExportJob | null>(null)
  const [polling, setPolling] = useState(true)

  useEffect(() => {
    if (!polling) return
    let cancelled = false

    async function poll() {
      try {
        const data = await exportApi.getJob(exportJobId)
        if (!cancelled) {
          setJob(data)
          if (data.status === 'done' || data.status === 'failed') {
            setPolling(false)
          }
        }
      } catch {
        if (!cancelled) setPolling(false)
      }
    }

    poll()
    const interval = setInterval(poll, 2000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [exportJobId, polling])

  const pct = job && job.total_assets > 0
    ? Math.round((job.exported_assets / job.total_assets) * 100)
    : 0

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="card p-6 w-full max-w-md mx-4">
        <h2 className="text-base font-semibold text-[var(--text-primary)] mb-4 flex items-center gap-2">
          <Package size={16} />
          Exporting Dataset
        </h2>

        {(!job || job.status === 'pending' || job.status === 'running') && (
          <>
            <div className="flex items-center gap-2 mb-3 text-sm text-[var(--text-secondary)]">
              <RefreshCw size={14} className="animate-spin" />
              {job
                ? `Exporting... ${job.exported_assets}/${job.total_assets} files`
                : 'Starting export...'}
            </div>
            <div className="h-2 rounded-full bg-[var(--border)] overflow-hidden">
              <div
                className="h-full rounded-full bg-[var(--accent)] transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="text-xs text-[var(--text-secondary)] mt-1 text-right">{pct}%</p>
          </>
        )}

        {job?.status === 'done' && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-green-400">
              <CheckCircle size={16} />
              <span className="text-sm font-medium">Export complete!</span>
            </div>
            <p className="text-xs text-[var(--text-secondary)]">
              {job.exported_assets} files exported
            </p>
            <a
              href={exportApi.downloadUrl(exportJobId)}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary flex items-center gap-2 w-full justify-center"
            >
              <Download size={14} /> Download ZIP
              <ExternalLink size={12} className="opacity-60" />
            </a>
          </div>
        )}

        {job?.status === 'failed' && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-red-400">
              <AlertTriangle size={16} />
              <span className="text-sm font-medium">Export failed</span>
            </div>
            {job.error && (
              <p className="text-xs text-[var(--text-secondary)] font-mono bg-red-950/30 p-2 rounded">
                {job.error}
              </p>
            )}
          </div>
        )}

        <button
          onClick={onClose}
          className="btn btn-secondary btn-sm mt-4 w-full"
          disabled={polling && job?.status !== 'done' && job?.status !== 'failed'}
        >
          {job?.status === 'done' || job?.status === 'failed' ? 'Close' : 'Cancel'}
        </button>
      </div>
    </div>
  )
}

// ── Validation Summary ─────────────────────────────────────────────────────────

function ValidationSummary({ validation }: { validation: ExportValidation | undefined }) {
  if (!validation) return null
  return (
    <div className="flex flex-wrap items-center gap-4 text-sm text-[var(--text-secondary)]">
      <span>
        <span className="text-[var(--text-primary)] font-medium">{validation.asset_count}</span>{' '}
        images
      </span>
      <span>
        <span className="text-[var(--text-primary)] font-medium">{validation.captioned_count}</span>{' '}
        captioned
      </span>
      <span>
        <span className="text-[var(--text-primary)] font-medium">{validation.approved_count}</span>{' '}
        approved
      </span>
      {validation.warnings.length > 0 && (
        <div className="flex items-center gap-1 text-yellow-400">
          <AlertTriangle size={13} />
          {validation.warnings.length} warning{validation.warnings.length !== 1 ? 's' : ''}
        </div>
      )}
    </div>
  )
}

// ── Shared form field styles ───────────────────────────────────────────────────

const inputCls =
  'w-full bg-transparent border border-[var(--border)] rounded px-3 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]'

const labelCls = 'block text-xs font-medium text-[var(--text-secondary)] mb-1 uppercase tracking-wide'

// ── Tab 1: LoRA ────────────────────────────────────────────────────────────────

function LoraTab({
  validation,
  onExportStart,
}: {
  validation: ExportValidation | undefined
  onExportStart: (jobId: string) => void
}) {
  const { activeProject } = useProjectStore()
  const { success, error: toastError } = useToast()

  const [triggerWord, setTriggerWord] = useState(activeProject?.trigger_word ?? '')
  const [repeats, setRepeats] = useState(10)
  const [captionStyle, setCaptionStyle] = useState('active')
  const [onlyCaptioned, setOnlyCaptioned] = useState(true)
  const [onlyApproved, setOnlyApproved] = useState(false)
  const [minScore, setMinScore] = useState(0)
  const [maxImages, setMaxImages] = useState<string>('')
  const [imageFormat, setImageFormat] = useState('PNG')
  const [datasetName, setDatasetName] = useState('')
  const [trainSplit, setTrainSplit] = useState(95)
  const [createZip, setCreateZip] = useState(true)
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: () => {
      if (!triggerWord.trim()) throw new Error('Trigger word is required')
      return exportApi.createLora(activeProject!.id, {
        trigger_word: triggerWord.trim(),
        repeats,
        caption_style: captionStyle,
        include_only_captioned: onlyCaptioned,
        include_only_approved: onlyApproved,
        min_score: minScore > 0 ? minScore : null,
        max_images: maxImages ? Number(maxImages) : null,
        image_format: imageFormat,
        create_zip: createZip,
        dataset_name: datasetName || undefined,
        train_split: trainSplit / 100,
      } as Parameters<typeof exportApi.createLora>[1])
    },
    onSuccess: data => {
      success(`Export started — ${data.asset_count} images`)
      onExportStart(data.export_job_id)
    },
    onError: (e: Error) => {
      setError(e.message || 'Export failed')
      toastError(e.message || 'Export failed')
    },
  })

  function handleExport() {
    setError('')
    if (!triggerWord.trim()) { setError('Trigger word is required'); return }
    mutation.mutate()
  }

  const estimatedCount =
    validation?.asset_count != null
      ? onlyCaptioned
        ? Math.min(
            validation.captioned_count,
            onlyApproved ? validation.approved_count : validation.captioned_count
          )
        : onlyApproved
        ? validation.approved_count
        : validation.asset_count
      : null

  return (
    <div className="space-y-5 max-w-xl">
      <div>
        <label className={labelCls}>Trigger Word *</label>
        <input
          type="text"
          value={triggerWord}
          onChange={e => setTriggerWord(e.target.value)}
          placeholder="e.g. ohwx person"
          className={inputCls}
        />
        {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
      </div>

      <div>
        <label className={labelCls}>Repeats: {repeats}</label>
        <input
          type="range"
          min={1}
          max={30}
          value={repeats}
          onChange={e => setRepeats(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
        />
        <div className="flex justify-between text-xs text-[var(--text-secondary)]">
          <span>1</span><span>30</span>
        </div>
      </div>

      <div>
        <label className={labelCls}>Caption Source</label>
        <select
          value={captionStyle}
          onChange={e => setCaptionStyle(e.target.value)}
          className={inputCls}
        >
          <option value="active">Active Caption</option>
          <option value="natural">Natural</option>
          <option value="danbooru_tags">Danbooru Tags</option>
          <option value="wd_tags">WD Tags</option>
        </select>
      </div>

      <div className="space-y-2">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={onlyCaptioned}
            onChange={e => setOnlyCaptioned(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          <span className="text-sm text-[var(--text-primary)]">Include only captioned</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={onlyApproved}
            onChange={e => setOnlyApproved(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          <span className="text-sm text-[var(--text-primary)]">Include only approved</span>
        </label>
      </div>

      <div>
        <label className={labelCls}>Min Score Filter: {Math.round(minScore * 100)}%</label>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={minScore}
          onChange={e => setMinScore(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
        />
      </div>

      <div>
        <label className={labelCls}>Max Images (optional)</label>
        <input
          type="number"
          min={1}
          value={maxImages}
          onChange={e => setMaxImages(e.target.value)}
          placeholder="No limit"
          className={inputCls}
        />
      </div>

      <div>
        <label className={labelCls}>Image Format</label>
        <div className="flex gap-2">
          {['PNG', 'JPG', 'WebP'].map(fmt => (
            <button
              key={fmt}
              onClick={() => setImageFormat(fmt)}
              className={`btn btn-sm ${imageFormat === fmt ? 'bg-[var(--accent)] text-white' : 'btn-secondary'}`}
            >
              {fmt}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className={labelCls}>Dataset Name</label>
        <input
          type="text"
          value={datasetName}
          onChange={e => setDatasetName(e.target.value)}
          placeholder="Optional name"
          className={inputCls}
        />
      </div>

      <div>
        <label className={labelCls}>
          Train / Validation Split:{' '}
          <span className="text-[var(--text-primary)] normal-case font-medium">
            {trainSplit}% train / {100 - trainSplit}% val
          </span>
        </label>
        <input
          type="range"
          min={80}
          max={100}
          step={5}
          value={trainSplit}
          onChange={e => setTrainSplit(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
        />
        <div className="flex justify-between text-xs text-[var(--text-secondary)]">
          <span>80% train</span><span>100% train</span>
        </div>
      </div>

      <label className="flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={createZip}
          onChange={e => setCreateZip(e.target.checked)}
          className="accent-[var(--accent)]"
        />
        <span className="text-sm text-[var(--text-primary)]">Create ZIP archive</span>
      </label>

      {estimatedCount != null && (
        <p className="text-sm text-[var(--text-secondary)]">
          Will export approximately{' '}
          <span className="text-[var(--text-primary)] font-medium">{estimatedCount}</span> images
        </p>
      )}

      <button
        onClick={handleExport}
        disabled={mutation.isPending || !activeProject}
        className="btn btn-primary flex items-center gap-2"
      >
        {mutation.isPending
          ? <RefreshCw size={14} className="animate-spin" />
          : <Download size={14} />}
        Export LoRA Dataset
      </button>
    </div>
  )
}

// ── Tab 2: Kohya SS ────────────────────────────────────────────────────────────

function KohyaTab({
  validation,
  onExportStart,
}: {
  validation: ExportValidation | undefined
  onExportStart: (jobId: string) => void
}) {
  const { activeProject } = useProjectStore()
  const { success, error: toastError } = useToast()

  const [triggerWord, setTriggerWord] = useState(activeProject?.trigger_word ?? '')
  const [repeats, setRepeats] = useState(10)
  const [datasetName, setDatasetName] = useState('')
  const [modelType, setModelType] = useState('sdxl')
  const [learningRate, setLearningRate] = useState('0.0001')
  const [epochs, setEpochs] = useState(10)
  const [batchSize, setBatchSize] = useState(1)
  const [networkRank, setNetworkRank] = useState(32)
  const [networkAlpha, setNetworkAlpha] = useState(16)
  const [generateScript, setGenerateScript] = useState(true)
  const [createZip, setCreateZip] = useState(true)
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: () => {
      if (!triggerWord.trim()) throw new Error('Trigger word is required')
      return exportApi.createKohya(activeProject!.id, {
        trigger_word: triggerWord.trim(),
        repeats,
        dataset_name: datasetName || undefined,
        model_type: modelType,
        learning_rate: Number(learningRate),
        epochs,
        batch_size: batchSize,
        network_rank: networkRank,
        network_alpha: networkAlpha,
        generate_train_script: generateScript,
        create_zip: createZip,
      })
    },
    onSuccess: data => {
      success(`Kohya export started — ${data.asset_count} images`)
      onExportStart(data.export_job_id)
    },
    onError: (e: Error) => {
      setError(e.message || 'Export failed')
      toastError(e.message || 'Export failed')
    },
  })

  function handleExport() {
    setError('')
    if (!triggerWord.trim()) { setError('Trigger word is required'); return }
    mutation.mutate()
  }

  const lrNum = Number(learningRate)
  const lrDisplay = !isNaN(lrNum) && lrNum > 0 ? lrNum.toExponential(4) : learningRate

  return (
    <div className="space-y-5 max-w-xl">
      <div>
        <label className={labelCls}>Trigger Word *</label>
        <input
          type="text"
          value={triggerWord}
          onChange={e => setTriggerWord(e.target.value)}
          placeholder="e.g. ohwx person"
          className={inputCls}
        />
        {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
      </div>

      <div>
        <label className={labelCls}>Repeats: {repeats}</label>
        <input
          type="range"
          min={1}
          max={30}
          value={repeats}
          onChange={e => setRepeats(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
        />
      </div>

      <div>
        <label className={labelCls}>Dataset Name</label>
        <input
          type="text"
          value={datasetName}
          onChange={e => setDatasetName(e.target.value)}
          placeholder="Optional"
          className={inputCls}
        />
      </div>

      <div>
        <label className={labelCls}>Model Type</label>
        <select
          value={modelType}
          onChange={e => setModelType(e.target.value)}
          className={inputCls}
        >
          <option value="sdxl">SDXL</option>
          <option value="sd15">SD 1.5</option>
          <option value="flux">Flux</option>
        </select>
      </div>

      <div>
        <label className={labelCls}>
          Learning Rate <span className="normal-case text-[var(--text-primary)]">{lrDisplay}</span>
        </label>
        <input
          type="text"
          value={learningRate}
          onChange={e => setLearningRate(e.target.value)}
          className={inputCls}
        />
      </div>

      <div>
        <label className={labelCls}>Epochs</label>
        <input
          type="number"
          min={1}
          max={200}
          value={epochs}
          onChange={e => setEpochs(Number(e.target.value))}
          className={inputCls}
        />
      </div>

      <div>
        <label className={labelCls}>Batch Size</label>
        <select
          value={batchSize}
          onChange={e => setBatchSize(Number(e.target.value))}
          className={inputCls}
        >
          {[1, 2, 4].map(v => <option key={v} value={v}>{v}</option>)}
        </select>
      </div>

      <div>
        <label className={labelCls}>Network Rank</label>
        <select
          value={networkRank}
          onChange={e => setNetworkRank(Number(e.target.value))}
          className={inputCls}
        >
          {[8, 16, 32, 64, 128].map(v => <option key={v} value={v}>{v}</option>)}
        </select>
      </div>

      <div>
        <label className={labelCls}>Network Alpha</label>
        <input
          type="number"
          min={1}
          max={128}
          value={networkAlpha}
          onChange={e => setNetworkAlpha(Number(e.target.value))}
          className={inputCls}
        />
      </div>

      <div className="space-y-2">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={generateScript}
            onChange={e => setGenerateScript(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          <span className="text-sm text-[var(--text-primary)]">Generate training script</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={createZip}
            onChange={e => setCreateZip(e.target.checked)}
            className="accent-[var(--accent)]"
          />
          <span className="text-sm text-[var(--text-primary)]">Create ZIP archive</span>
        </label>
      </div>

      {validation && (
        <p className="text-sm text-[var(--text-secondary)]">
          Will export approximately{' '}
          <span className="text-[var(--text-primary)] font-medium">{validation.asset_count}</span> images
        </p>
      )}

      <button
        onClick={handleExport}
        disabled={mutation.isPending || !activeProject}
        className="btn btn-primary flex items-center gap-2"
      >
        {mutation.isPending
          ? <RefreshCw size={14} className="animate-spin" />
          : <Download size={14} />}
        Export Kohya SS
      </button>
    </div>
  )
}

// ── Tab 3: ZIP Archive ─────────────────────────────────────────────────────────

function ZipTab({
  onExportStart,
}: {
  onExportStart: (jobId: string) => void
}) {
  const { activeProject } = useProjectStore()
  const { selectedIds } = useAssetStore()
  const { success, error: toastError } = useToast()

  const [datasetName, setDatasetName] = useState('')
  const [includeMetadata, setIncludeMetadata] = useState(true)
  const [scope, setScope] = useState<'all' | 'selected'>('all')

  const mutation = useMutation({
    mutationFn: () =>
      exportApi.createZip(activeProject!.id, {
        dataset_name: datasetName || undefined,
        include_metadata: includeMetadata,
        asset_ids: scope === 'selected' ? Array.from(selectedIds) : undefined,
      }),
    onSuccess: data => {
      success(`ZIP export started — ${data.asset_count} images`)
      onExportStart(data.export_job_id)
    },
    onError: () => toastError('Export failed'),
  })

  return (
    <div className="space-y-5 max-w-xl">
      <div>
        <label className={labelCls}>Dataset Name</label>
        <input
          type="text"
          value={datasetName}
          onChange={e => setDatasetName(e.target.value)}
          placeholder="Optional archive name"
          className={inputCls}
        />
      </div>

      <label className="flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={includeMetadata}
          onChange={e => setIncludeMetadata(e.target.checked)}
          className="accent-[var(--accent)]"
        />
        <span className="text-sm text-[var(--text-primary)]">Include metadata JSON</span>
      </label>

      <div>
        <label className={labelCls}>Asset Scope</label>
        <div className="flex gap-2">
          <button
            onClick={() => setScope('all')}
            className={`btn btn-sm ${scope === 'all' ? 'bg-[var(--accent)] text-white' : 'btn-secondary'}`}
          >
            All
          </button>
          <button
            onClick={() => setScope('selected')}
            disabled={selectedIds.size === 0}
            className={`btn btn-sm ${scope === 'selected' ? 'bg-[var(--accent)] text-white' : 'btn-secondary'} disabled:opacity-40`}
          >
            Selected only ({selectedIds.size})
          </button>
        </div>
      </div>

      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending || !activeProject}
        className="btn btn-primary flex items-center gap-2"
      >
        {mutation.isPending
          ? <RefreshCw size={14} className="animate-spin" />
          : <Package size={14} />}
        Export ZIP
      </button>
    </div>
  )
}

// ── Tab 3b: SimpleTuner ────────────────────────────────────────────────────────

function SimpleTunerTab({
  validation,
  onExportStart,
}: {
  validation: ExportValidation | undefined
  onExportStart: (jobId: string) => void
}) {
  const { activeProject } = useProjectStore()
  const { success, error: toastError } = useToast()

  const [triggerWord, setTriggerWord] = useState(activeProject?.trigger_word ?? '')
  const [datasetName, setDatasetName] = useState('')
  const [captionStyle, setCaptionStyle] = useState('active')
  const [onlyApproved, setOnlyApproved] = useState(false)
  const [minScore, setMinScore] = useState(0)
  const [trainSplit, setTrainSplit] = useState(95)
  const [createZip, setCreateZip] = useState(true)
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: () => {
      if (!triggerWord.trim()) throw new Error('Trigger word is required')
      return exportApi.create({
        project_id: activeProject!.id,
        export_format: 'simpletuner',
        options: {
          trigger_word: triggerWord.trim(),
          dataset_name: datasetName || undefined,
          caption_style: captionStyle,
          include_only_approved: onlyApproved,
          min_score: minScore > 0 ? minScore : null,
          train_split: trainSplit / 100,
          create_zip: createZip,
        },
      })
    },
    onSuccess: data => {
      success(`SimpleTuner export started — ${data.asset_count} images`)
      onExportStart(data.export_job_id)
    },
    onError: (e: Error) => {
      setError(e.message || 'Export failed')
      toastError(e.message || 'Export failed')
    },
  })

  function handleExport() {
    setError('')
    if (!triggerWord.trim()) { setError('Trigger word is required'); return }
    mutation.mutate()
  }

  return (
    <div className="space-y-5 max-w-xl">
      <p className="text-xs text-[var(--text-secondary)]">
        Exports an aspect-ratio bucketed dataset compatible with SimpleTuner, including a{' '}
        <code className="font-mono">dataset_config.json</code> and per-image caption files.
      </p>

      <div>
        <label className={labelCls}>Trigger Word *</label>
        <input
          type="text"
          value={triggerWord}
          onChange={e => setTriggerWord(e.target.value)}
          placeholder="e.g. ohwx person"
          className={inputCls}
        />
        {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
      </div>

      <div>
        <label className={labelCls}>Dataset Name</label>
        <input
          type="text"
          value={datasetName}
          onChange={e => setDatasetName(e.target.value)}
          placeholder="Optional"
          className={inputCls}
        />
      </div>

      <div>
        <label className={labelCls}>Caption Source</label>
        <select
          value={captionStyle}
          onChange={e => setCaptionStyle(e.target.value)}
          className={inputCls}
        >
          <option value="active">Active Caption</option>
          <option value="natural">Natural</option>
          <option value="danbooru_tags">Danbooru Tags</option>
          <option value="wd_tags">WD Tags</option>
        </select>
      </div>

      <label className="flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={onlyApproved}
          onChange={e => setOnlyApproved(e.target.checked)}
          className="accent-[var(--accent)]"
        />
        <span className="text-sm text-[var(--text-primary)]">Include only approved</span>
      </label>

      <div>
        <label className={labelCls}>Min Score Filter: {Math.round(minScore * 100)}%</label>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={minScore}
          onChange={e => setMinScore(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
        />
      </div>

      <div>
        <label className={labelCls}>
          Train / Validation Split:{' '}
          <span className="text-[var(--text-primary)] normal-case font-medium">
            {trainSplit}% train / {100 - trainSplit}% val
          </span>
        </label>
        <input
          type="range"
          min={80}
          max={100}
          step={5}
          value={trainSplit}
          onChange={e => setTrainSplit(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
        />
      </div>

      <label className="flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={createZip}
          onChange={e => setCreateZip(e.target.checked)}
          className="accent-[var(--accent)]"
        />
        <span className="text-sm text-[var(--text-primary)]">Create ZIP archive</span>
      </label>

      {validation && (
        <p className="text-sm text-[var(--text-secondary)]">
          Will export approximately{' '}
          <span className="text-[var(--text-primary)] font-medium">{validation.asset_count}</span> images
        </p>
      )}

      <button
        onClick={handleExport}
        disabled={mutation.isPending || !activeProject}
        className="btn btn-primary flex items-center gap-2"
      >
        {mutation.isPending
          ? <RefreshCw size={14} className="animate-spin" />
          : <Download size={14} />}
        Export SimpleTuner
      </button>
    </div>
  )
}

// ── Tab 4: Custom (placeholder) ────────────────────────────────────────────────

function CustomTab() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-[var(--text-secondary)]">
      <Settings size={36} className="mb-3 opacity-40" />
      <p className="font-medium">Custom export coming soon</p>
      <p className="text-xs mt-1">Configure fully custom export pipelines here.</p>
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function Export() {
  const { activeProject } = useProjectStore()
  const [activeTab, setActiveTab] = useState<TabName>('LoRA Dataset')
  const [activeExportJobId, setActiveExportJobId] = useState<string | null>(null)

  const { data: validation } = useQuery({
    queryKey: ['export-validation', activeProject?.id],
    queryFn: () => exportApi.validate(activeProject!.id),
    enabled: !!activeProject?.id,
    staleTime: 30_000,
  })

  function handleExportStart(jobId: string) {
    setActiveExportJobId(jobId)
  }

  if (!activeProject) {
    return (
      <div className="p-6 flex items-center justify-center h-full">
        <p className="text-[var(--text-secondary)]">Select a project to export.</p>
      </div>
    )
  }

  return (
    <div className="p-6 overflow-y-auto h-full">
      {/* Header */}
      <div className="flex items-start justify-between mb-2">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">Export Dataset</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Package your curated dataset for training
          </p>
        </div>
      </div>

      {/* Validation summary */}
      {validation && (
        <div className="mb-5">
          <ValidationSummary validation={validation} />
          {validation.warnings.map((w, i) => (
            <p key={i} className="text-xs text-yellow-400 flex items-center gap-1 mt-1">
              <AlertTriangle size={12} /> {w}
            </p>
          ))}
        </div>
      )}

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

      {activeTab === 'LoRA Dataset' && (
        <LoraTab validation={validation} onExportStart={handleExportStart} />
      )}
      {activeTab === 'Kohya SS' && (
        <KohyaTab validation={validation} onExportStart={handleExportStart} />
      )}
      {activeTab === 'SimpleTuner' && (
        <SimpleTunerTab validation={validation} onExportStart={handleExportStart} />
      )}
      {activeTab === 'ZIP Archive' && (
        <ZipTab onExportStart={handleExportStart} />
      )}
      {activeTab === 'Custom' && <CustomTab />}

      {/* Progress Modal */}
      {activeExportJobId && (
        <ProgressModal
          exportJobId={activeExportJobId}
          onClose={() => setActiveExportJobId(null)}
        />
      )}
    </div>
  )
}
