import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle,
  XCircle,
  RefreshCw,
  Eye,
  EyeOff,
  TestTube,
  Plus,
  AlertTriangle,
  Database,
  Trash2,
  Server,
  Key,
  Sliders,
  FolderOpen,
} from 'lucide-react'
import { adminApi, projectsApi, providersApi } from '@/hooks/useApi'
import { useProjectStore } from '@/stores/useProjectStore'
import { useToast } from '@/components/providers/ToastProvider'

// ── useSetting hook ────────────────────────────────────────────────────────────

function useSetting<T>(key: string, defaultValue: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(`draco_setting_${key}`)
      if (stored !== null) return JSON.parse(stored) as T
    } catch {
      // ignore
    }
    return defaultValue
  })

  function set(v: T) {
    setValue(v)
    try {
      localStorage.setItem(`draco_setting_${key}`, JSON.stringify(v))
    } catch {
      // ignore
    }
  }

  return [value, set]
}

// ── Shared styles ──────────────────────────────────────────────────────────────

const inputCls =
  'w-full bg-transparent border border-[var(--border)] rounded px-3 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]'

const labelCls = 'block text-xs font-medium text-[var(--text-secondary)] mb-1 uppercase tracking-wide'

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
      {children}
    </h2>
  )
}

// ── Provider Status Dot ────────────────────────────────────────────────────────

function StatusDot({ ok, latency }: { ok: boolean | undefined; latency?: number }) {
  if (ok === undefined) return <span className="w-2 h-2 rounded-full bg-[var(--border)] inline-block" />
  return (
    <span className="flex items-center gap-1.5">
      <span className={`w-2 h-2 rounded-full inline-block ${ok ? 'bg-green-400' : 'bg-red-400'}`} />
      {ok ? (
        <CheckCircle size={13} className="text-green-400" />
      ) : (
        <XCircle size={13} className="text-red-400" />
      )}
      {latency != null && (
        <span className="text-xs text-[var(--text-secondary)]">{latency}ms</span>
      )}
    </span>
  )
}

// ── Section 1: Provider Health ─────────────────────────────────────────────────

function ProjectRuntimeSection() {
  const activeProjectId = useProjectStore((s) => s.activeProjectId)
  const activeProject = useProjectStore((s) =>
    s.projects.find((project) => project.id === s.activeProjectId) ?? null
  )
  const queryClient = useQueryClient()
  const { success, error: toastError } = useToast()

  const { data, isLoading } = useQuery({
    queryKey: ['project-runtime', activeProjectId],
    queryFn: () => projectsApi.getRuntime(activeProjectId!),
    enabled: !!activeProjectId,
    staleTime: 30_000,
  })

  const updateMutation = useMutation({
    mutationFn: (
      patch: Partial<{
        runtime_mode: 'local' | 'hybrid' | 'hosted'
        task_provider_overrides: Record<string, string>
        task_provider_options: Record<string, Record<string, unknown>>
      }>
    ) => projectsApi.updateRuntime(activeProjectId!, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-runtime', activeProjectId] })
      success('Project runtime updated')
    },
    onError: (e: Error) => {
      toastError(e.message || 'Failed to update project runtime')
    },
  })

  function saveRuntimeMode(runtimeMode: 'local' | 'hybrid' | 'hosted') {
    updateMutation.mutate({ runtime_mode: runtimeMode })
  }

  function saveTaskProvider(taskKey: string, providerName: string) {
    if (!data) return
    const nextOverrides = { ...data.task_provider_overrides }
    if (providerName) nextOverrides[taskKey] = providerName
    else delete nextOverrides[taskKey]
    updateMutation.mutate({ task_provider_overrides: nextOverrides })
  }

  function saveTaskOptions(taskKey: string, patch: Record<string, unknown>) {
    if (!data) return
    updateMutation.mutate({
      task_provider_options: {
        ...data.task_provider_options,
        [taskKey]: {
          ...(data.task_provider_options[taskKey] ?? {}),
          ...patch,
        },
      },
    })
  }

  return (
    <section className="mb-8">
      <SectionTitle>
        <Server size={15} />
        Project Runtime
      </SectionTitle>

      {!activeProjectId || !activeProject ? (
        <p className="text-sm text-[var(--text-secondary)]">
          Select a project to configure task-specific providers and Ollama defaults.
        </p>
      ) : isLoading ? (
        <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <RefreshCw size={14} className="animate-spin" /> Loading project runtime...
        </div>
      ) : data ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">
              Active Project
            </span>
            <span className="text-sm text-[var(--text-primary)]">{activeProject.name}</span>
          </div>

          <div>
            <label className={labelCls}>Runtime Mode</label>
            <select
              value={data.runtime_mode}
              onChange={(e) => saveRuntimeMode(e.target.value as 'local' | 'hybrid' | 'hosted')}
              className={inputCls}
            >
              <option value="local">Local-only</option>
              <option value="hybrid">Hybrid</option>
              <option value="hosted">Hosted / Server</option>
            </select>
          </div>

          {data.task_catalog.map((task) => (
            <div key={task.task_key} className="rounded border border-[var(--border)] p-3 bg-[var(--border)]/10">
              <div className="flex items-start justify-between gap-3 mb-2">
                <div>
                  <p className="text-sm font-medium text-[var(--text-primary)]">{task.label}</p>
                  <p className="text-xs text-[var(--text-secondary)]">{task.description}</p>
                </div>
                <span className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">
                  {task.provider_type}
                </span>
              </div>

              <label className={labelCls}>Provider</label>
              <select
                value={data.task_provider_overrides[task.task_key] ?? ''}
                onChange={(e) => saveTaskProvider(task.task_key, e.target.value)}
                className={inputCls}
              >
                <option value="">Auto ({task.effective_provider ?? 'none'})</option>
                {task.available_providers.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>

              {['caption', 'ranking_explanation', 'dataset_coach'].includes(task.task_key) && (
                <div className="grid grid-cols-2 gap-2 mt-3">
                  <div>
                    <label className={labelCls}>Model</label>
                    <input
                      key={`${task.task_key}-model-${String(data.task_provider_options[task.task_key]?.model ?? '')}`}
                      defaultValue={String(data.task_provider_options[task.task_key]?.model ?? '')}
                      onBlur={(e) => saveTaskOptions(task.task_key, { model: e.target.value })}
                      className={inputCls}
                      placeholder="llava:13b"
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Temperature</label>
                    <input
                      key={`${task.task_key}-temp-${String(data.task_provider_options[task.task_key]?.temperature ?? '')}`}
                      type="number"
                      step="0.05"
                      min="0"
                      max="2"
                      defaultValue={String(data.task_provider_options[task.task_key]?.temperature ?? 0.1)}
                      onBlur={(e) => saveTaskOptions(task.task_key, { temperature: Number(e.target.value) })}
                      className={inputCls}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Context Length</label>
                    <input
                      key={`${task.task_key}-ctx-${String(data.task_provider_options[task.task_key]?.context_length ?? '')}`}
                      type="number"
                      min="256"
                      step="256"
                      defaultValue={String(data.task_provider_options[task.task_key]?.context_length ?? 4096)}
                      onBlur={(e) => saveTaskOptions(task.task_key, { context_length: Number(e.target.value) })}
                      className={inputCls}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Max Tokens</label>
                    <input
                      key={`${task.task_key}-max-${String(data.task_provider_options[task.task_key]?.max_tokens ?? '')}`}
                      type="number"
                      min="64"
                      step="64"
                      defaultValue={String(data.task_provider_options[task.task_key]?.max_tokens ?? 512)}
                      onBlur={(e) => saveTaskOptions(task.task_key, { max_tokens: Number(e.target.value) })}
                      className={inputCls}
                    />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function ProviderHealthSection() {
  const {
    data: health,
    isLoading,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['provider-health'],
    queryFn: () => providersApi.health(),
    staleTime: 30_000,
  })

  return (
    <section className="mb-8">
      <div className="flex items-center justify-between mb-3">
        <SectionTitle>
          <Server size={15} />
          Provider Status
        </SectionTitle>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="btn btn-sm btn-secondary flex items-center gap-1"
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <RefreshCw size={14} className="animate-spin" /> Loading providers...
        </div>
      )}

      {health && (
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
          {Object.entries(health.providers).flatMap(([type, providerMap]) =>
            Object.entries(providerMap).map(([name, status]) => (
              <div
                key={`${type}-${name}`}
                className="flex items-center justify-between p-2 rounded border border-[var(--border)] bg-[var(--border)]/10"
              >
                <div>
                  <p className="text-xs font-medium text-[var(--text-primary)] capitalize">{type}</p>
                  <p className="text-xs text-[var(--text-secondary)]">{name}</p>
                </div>
                <StatusDot ok={status.ok} latency={status.latency_ms} />
              </div>
            ))
          )}
        </div>
      )}

      {health && Object.keys(health.providers).length === 0 && (
        <p className="text-sm text-[var(--text-secondary)]">No providers configured.</p>
      )}
    </section>
  )
}

// ── Section 2: Caption Providers ───────────────────────────────────────────────

function CaptionProvidersSection() {
  const { data, isLoading } = useQuery({
    queryKey: ['caption-models'],
    queryFn: () => providersApi.captionModels(),
    staleTime: 60_000,
  })

  const [testResults, setTestResults] = useState<
    Record<string, { ok: boolean; latency_ms: number } | 'testing'>
  >({})

  async function testProvider(name: string) {
    setTestResults(r => ({ ...r, [name]: 'testing' }))
    try {
      const result = await providersApi.testProvider('caption', name)
      setTestResults(r => ({ ...r, [name]: result }))
    } catch {
      setTestResults(r => ({ ...r, [name]: { ok: false, latency_ms: 0 } }))
    }
  }

  return (
    <section className="mb-8">
      <SectionTitle>
        <TestTube size={15} />
        Caption Providers
      </SectionTitle>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <RefreshCw size={14} className="animate-spin" /> Loading providers...
        </div>
      )}

      {data && (
        <div className="space-y-2">
          {Object.entries(data.providers).map(([name, models]) => {
            const testResult = testResults[name]
            return (
              <div key={name} className="p-3 rounded border border-[var(--border)]">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-[var(--text-primary)] capitalize">
                    {name}
                  </span>
                  <div className="flex items-center gap-2">
                    {testResult === 'testing' && (
                      <RefreshCw size={12} className="animate-spin text-[var(--text-secondary)]" />
                    )}
                    {testResult && testResult !== 'testing' && (
                      <StatusDot ok={testResult.ok} latency={testResult.latency_ms} />
                    )}
                    <button
                      onClick={() => testProvider(name)}
                      disabled={testResult === 'testing'}
                      className="btn btn-sm btn-secondary"
                    >
                      Test
                    </button>
                  </div>
                </div>
                {Array.isArray(models) && models.length > 0 && (
                  <p className="text-xs text-[var(--text-secondary)]">
                    Models: {(models as unknown[]).map(m =>
                      typeof m === 'string' ? m : (m as { name?: string })?.name ?? String(m)
                    ).join(', ')}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

// ── Section 3: API Keys ────────────────────────────────────────────────────────

interface ApiKeyRowProps {
  label: string
  providerType: string
  providerName: string
  placeholder?: string
  hasKey?: boolean
}

function ApiKeyRow({ label, providerType, providerName, placeholder, hasKey }: ApiKeyRowProps) {
  const [draft, setDraft] = useState('')
  const [show, setShow] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  async function handleSave() {
    if (!draft.trim()) return
    setSaving(true)
    setError(null)
    try {
      await providersApi.saveApiKey(providerType, providerName, draft)
      setDraft('')
      setSaved(true)
      queryClient.invalidateQueries({ queryKey: ['api-key-status'] })
      setTimeout(() => setSaved(false), 2000)
    } catch (_e) {
      setError('Failed to save key')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <label className={labelCls}>
        {label}
        {hasKey && (
          <span className="ml-2 text-green-400 font-normal normal-case tracking-normal">
            ✓ key stored
          </span>
        )}
      </label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={show ? 'text' : 'password'}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder={hasKey ? '••••••••••••••••' : (placeholder ?? `Enter ${label} API key`)}
            className={inputCls}
          />
          <button
            onClick={() => setShow(p => !p)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            {show ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
        <button
          onClick={handleSave}
          disabled={saving || !draft.trim()}
          className={`btn btn-sm flex items-center gap-1 ${saved ? 'btn-secondary text-green-400' : 'btn-secondary'}`}
        >
          {saved ? <CheckCircle size={12} /> : null}
          {saving ? 'Saving…' : saved ? 'Saved' : 'Save'}
        </button>
      </div>
      {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
    </div>
  )
}

function ApiKeysSection() {
  const { data: keyStatus } = useQuery({
    queryKey: ['api-key-status'],
    queryFn: () => providersApi.getApiKeyStatus(),
    staleTime: 30_000,
  })

  const status = keyStatus?.status ?? {}

  return (
    <section className="mb-8">
      <SectionTitle>
        <Key size={15} />
        API Keys
      </SectionTitle>
      <p className="text-xs text-[var(--text-secondary)] mb-3">
        Keys are encrypted and stored in the local backend database. They are never sent to Draco servers.
      </p>
      <div className="space-y-4">
        <ApiKeyRow label="OpenAI" providerType="caption" providerName="openai" placeholder="sk-..." hasKey={status['openai']} />
        <ApiKeyRow label="Gemini" providerType="caption" providerName="gemini" placeholder="AIza..." hasKey={status['gemini']} />
        <ApiKeyRow label="HuggingFace" providerType="caption" providerName="huggingface" placeholder="hf_..." hasKey={status['huggingface']} />
      </div>
    </section>
  )
}

// ── Section 4: Editing Providers ───────────────────────────────────────────────

function EditingProvidersSection() {
  const queryClient = useQueryClient()
  const { success, error: toastError } = useToast()
  const [testResult, setTestResult] = useState<{ ok: boolean; latency_ms: number } | 'testing' | null>(null)
  const { data: providerConfigs } = useQuery({
    queryKey: ['provider-configs'],
    queryFn: () => providersApi.configs(),
    staleTime: 30_000,
  })

  const comfyConfig = providerConfigs?.configs?.editing?.comfyui
  const [draft, setDraft] = useState('http://localhost:8188')

  React.useEffect(() => {
    const configured = comfyConfig?.config?.base_url
    if (typeof configured === 'string' && configured.trim()) {
      setDraft(configured)
    }
  }, [comfyConfig?.config])

  async function testConnection() {
    if (!draft.trim()) {
      setTestResult({ ok: false, latency_ms: 0 })
      toastError('ComfyUI endpoint is required')
      return
    }
    setTestResult('testing')
    try {
      await providersApi.saveConfig('editing', {
        provider_name: 'comfyui',
        base_url: draft.trim(),
      })
      await queryClient.invalidateQueries({ queryKey: ['provider-configs'] })
      const r = await providersApi.testProvider('editing', 'comfyui')
      setTestResult(r)
      if (r.ok) {
        success('ComfyUI endpoint saved and reachable')
      } else {
        toastError('ComfyUI endpoint saved, but the provider is not reachable')
      }
    } catch {
      setTestResult({ ok: false, latency_ms: 0 })
      toastError('Failed to save or test the ComfyUI endpoint')
    }
  }

  return (
    <section className="mb-8">
      <SectionTitle>
        <Sliders size={15} />
        Editing Providers
      </SectionTitle>
      <div>
        <label className={labelCls}>ComfyUI Endpoint</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={draft}
            onChange={e => setDraft(e.target.value)}
            className={`${inputCls} flex-1`}
          />
          <button
            onClick={testConnection}
            disabled={testResult === 'testing'}
            className="btn btn-sm btn-secondary flex items-center gap-1"
          >
            {testResult === 'testing'
              ? <RefreshCw size={12} className="animate-spin" />
              : <TestTube size={12} />}
            Test
          </button>
        </div>
        {testResult && testResult !== 'testing' && (
          <p className={`text-xs mt-1 flex items-center gap-1 ${testResult.ok ? 'text-green-400' : 'text-red-400'}`}>
            {testResult.ok
              ? <><CheckCircle size={12} /> Available ({testResult.latency_ms}ms)</>
              : <><XCircle size={12} /> Not available</>}
          </p>
        )}
      </div>
    </section>
  )
}

// ── Section 5: Performance ─────────────────────────────────────────────────────

function PerformanceSection() {
  const [maxWorkers, setMaxWorkers] = useSetting('max_workers', 4)
  const [vramBudget, setVramBudget] = useSetting('vram_budget', '8GB')
  const [thumbSize, setThumbSize] = useSetting('thumbnail_size', '256px')

  return (
    <section className="mb-8">
      <SectionTitle>
        <Sliders size={15} />
        Performance
      </SectionTitle>
      <p className="text-xs text-gray-500 mb-3">These are configured server-side via environment variables (MAX_WORKERS, VRAM_BUDGET_MB, THUMBNAIL_SIZE).</p>
      <div className="space-y-4">
        <div>
          <label className={labelCls}>Max Workers</label>
          <input
            type="number"
            min={1}
            max={16}
            value={maxWorkers}
            onChange={e => setMaxWorkers(Number(e.target.value))}
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>VRAM Budget</label>
          <select
            value={vramBudget}
            onChange={e => setVramBudget(e.target.value)}
            className={inputCls}
          >
            {['4GB', '8GB', '12GB', '16GB', '24GB', 'Unlimited'].map(v => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>Thumbnail Size</label>
          <select
            value={thumbSize}
            onChange={e => setThumbSize(e.target.value)}
            className={inputCls}
          >
            {['128px', '256px', '512px'].map(v => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </div>
      </div>
    </section>
  )
}

// ── Section 6: Export Defaults ─────────────────────────────────────────────────

function ExportDefaultsSection() {
  const [triggerWord, setTriggerWord] = useSetting('default_trigger_word', '')
  const [format, setFormat] = useSetting('default_export_format', 'LoRA')
  const [repeats, setRepeats] = useSetting('default_repeats', 10)

  return (
    <section className="mb-8">
      <SectionTitle>
        <FolderOpen size={15} />
        Export Defaults
      </SectionTitle>
      <div className="space-y-4">
        <div>
          <label className={labelCls}>Default Trigger Word</label>
          <input
            type="text"
            value={triggerWord}
            onChange={e => setTriggerWord(e.target.value)}
            placeholder="e.g. ohwx person"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>Default Format</label>
          <select
            value={format}
            onChange={e => setFormat(e.target.value)}
            className={inputCls}
          >
            {['LoRA', 'Kohya SS', 'ZIP'].map(f => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>Default Repeats: {repeats}</label>
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
      </div>
    </section>
  )
}

// ── Section 7: Data Management ─────────────────────────────────────────────────

function DataManagementSection() {
  const { success, error: toastError } = useToast()
  const [confirmVacuum, setConfirmVacuum] = useState(false)
  const { data: storageInfo } = useQuery({
    queryKey: ['storage-info'],
    queryFn: () => adminApi.storageInfo(),
    staleTime: 60_000,
  })

  async function handleClearThumbs() {
    try {
      const data = await adminApi.clearThumbnails()
      success(`Thumbnail cache cleared (${data.deleted ?? 0} files)`)
    } catch (e) {
      toastError(`Failed to clear thumbnails: ${e instanceof Error ? e.message : 'unknown error'}`)
    }
  }

  async function handleVacuum() {
    if (!confirmVacuum) { setConfirmVacuum(true); return }
    try {
      await adminApi.vacuum()
      success('Database vacuumed')
      setConfirmVacuum(false)
    } catch (e) {
      toastError(`Vacuum failed: ${e instanceof Error ? e.message : 'unknown error'}`)
      setConfirmVacuum(false)
    }
  }

  return (
    <section className="mb-8">
      <SectionTitle>
        <Database size={15} />
        Data Management
      </SectionTitle>
      <div className="space-y-3">
        <div>
          <p className="text-xs text-[var(--text-secondary)] mb-1 uppercase tracking-wide font-medium">
            Storage Path
          </p>
          <p className="text-sm text-[var(--text-primary)] font-mono bg-[var(--border)]/20 px-3 py-1.5 rounded border border-[var(--border)]">
            {storageInfo?.storage_path ?? 'Loading…'}
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <button
            onClick={handleClearThumbs}
            className="btn btn-secondary btn-sm flex items-center gap-2 w-fit"
          >
            <Trash2 size={13} />
            Clear Thumbnail Cache
          </button>

          <button
            onClick={handleVacuum}
            className={`btn btn-sm flex items-center gap-2 w-fit ${
              confirmVacuum ? 'btn-danger' : 'btn-secondary'
            }`}
          >
            <AlertTriangle size={13} />
            {confirmVacuum ? 'Click again to confirm vacuum' : 'Vacuum Database'}
          </button>
          {confirmVacuum && (
            <p className="text-xs text-yellow-400 flex items-center gap-1">
              <AlertTriangle size={11} />
              This will compact the database. May take a moment.
            </p>
          )}
        </div>
      </div>
    </section>
  )
}

// ── Section 8: Create Project ──────────────────────────────────────────────────

function CreateProjectSection() {
  const { success, error: toastError } = useToast()
  const { addProject, setActiveProject } = useProjectStore()
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [triggerWord, setTriggerWord] = useState('')
  const [nameError, setNameError] = useState('')

  const createMutation = useMutation({
    mutationFn: () => {
      if (!name.trim()) throw new Error('Name is required')
      return projectsApi.create({
        name: name.trim(),
        trigger_word: triggerWord.trim() || undefined,
      })
    },
    onSuccess: project => {
      addProject(project)
      setActiveProject(project.id)
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      success(`Project "${project.name}" created`)
      setName('')
      setTriggerWord('')
      setNameError('')
    },
    onError: (e: Error) => {
      setNameError(e.message)
      toastError(e.message || 'Failed to create project')
    },
  })

  function handleCreate() {
    setNameError('')
    if (!name.trim()) { setNameError('Name is required'); return }
    createMutation.mutate()
  }

  return (
    <section className="mb-8">
      <SectionTitle>
        <Plus size={15} />
        Create New Project
      </SectionTitle>
      <div className="space-y-3 max-w-sm">
        <div>
          <label className={labelCls}>Project Name *</label>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleCreate() }}
            placeholder="My Dataset"
            className={inputCls}
          />
          {nameError && <p className="text-xs text-red-400 mt-1">{nameError}</p>}
        </div>
        <div>
          <label className={labelCls}>Trigger Word</label>
          <input
            type="text"
            value={triggerWord}
            onChange={e => setTriggerWord(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleCreate() }}
            placeholder="e.g. ohwx person"
            className={inputCls}
          />
        </div>
        <button
          onClick={handleCreate}
          disabled={createMutation.isPending}
          className="btn btn-primary flex items-center gap-2"
        >
          {createMutation.isPending
            ? <RefreshCw size={14} className="animate-spin" />
            : <Plus size={14} />}
          Create Project
        </button>
      </div>
    </section>
  )
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function Settings() {
  return (
    <div className="p-6 overflow-y-auto h-full max-w-3xl">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Settings</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Configure providers, performance, and project defaults
        </p>
      </div>

      <ProjectRuntimeSection />
      <ProviderHealthSection />
      <CaptionProvidersSection />
      <ApiKeysSection />
      <EditingProvidersSection />
      <PerformanceSection />
      <ExportDefaultsSection />
      <DataManagementSection />
      <CreateProjectSection />
    </div>
  )
}
