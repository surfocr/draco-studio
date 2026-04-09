/**
 * First-run setup wizard.
 * Detects first launch via localStorage and walks the user through configuring
 * at least one caption provider (local via Ollama, or via API keys).
 */
import React, { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Cpu,
  Key,
  Layers,
  CheckCircle,
  XCircle,
  RefreshCw,
  ChevronRight,
  ChevronLeft,
  ArrowRight,
  Eye,
  EyeOff,
  Copy,
  Check,
  Zap,
  Globe,
  Download,
  Server,
  AlertTriangle,
  SkipForward,
} from 'lucide-react'
import { providersApi } from '@/hooks/useApi'
import { useProjectStore } from '@/stores/useProjectStore'

// ── Types ─────────────────────────────────────────────────────────────────────

type WizardMode = 'local' | 'api' | 'both'

// ── Helpers ───────────────────────────────────────────────────────────────────

const inputCls =
  'w-full bg-transparent border border-[var(--border)] rounded px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] transition-colors'

function completeSetup() {
  try {
    localStorage.setItem('draco_setup_complete', '1')
  } catch {
    // ignore storage errors
  }
}

// ── Recommended Ollama models ─────────────────────────────────────────────────

interface OllamaModel {
  id: string
  label: string
  tag: string
  description: string
  size: string
  recommended?: boolean
}

const OLLAMA_MODELS: OllamaModel[] = [
  {
    id: 'llava',
    label: 'LLaVA 7B',
    tag: 'llava',
    description: 'Fast, general-purpose vision-language model. Great starting point.',
    size: '~4.7 GB',
    recommended: true,
  },
  {
    id: 'llava13b',
    label: 'LLaVA 13B',
    tag: 'llava:13b',
    description: 'Higher quality captions than 7B. Needs more VRAM.',
    size: '~8.0 GB',
  },
  {
    id: 'bakllava',
    label: 'BakLLaVA',
    tag: 'bakllava',
    description: 'Mistral-based VLM, good at following detailed instructions.',
    size: '~4.1 GB',
  },
  {
    id: 'moondream',
    label: 'Moondream 2',
    tag: 'moondream',
    description: 'Tiny 1.8B model. Runs on CPU. Lower quality but very fast.',
    size: '~1.7 GB',
  },
  {
    id: 'llava-phi3',
    label: 'LLaVA-Phi3',
    tag: 'llava-phi3',
    description: 'Phi-3 base, compact yet surprisingly capable.',
    size: '~2.9 GB',
  },
]

// ── Copy-to-clipboard button ──────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <button
      onClick={handleCopy}
      title="Copy command"
      className="p-1 rounded text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--border)] transition-colors"
    >
      {copied ? <Check size={13} className="text-green-400" /> : <Copy size={13} />}
    </button>
  )
}

// ── Step 0: Welcome ───────────────────────────────────────────────────────────

function WelcomeStep({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  return (
    <div className="flex flex-col items-center text-center max-w-md mx-auto">
      <div className="w-16 h-16 rounded-2xl bg-[var(--accent)]/20 border border-[var(--accent)]/30 flex items-center justify-center mb-6">
        <Layers size={32} className="text-[var(--accent)]" />
      </div>
      <h1 className="text-2xl font-bold text-[var(--text-primary)] mb-2">Welcome to Draco Studio</h1>
      <p className="text-[var(--text-secondary)] text-sm leading-relaxed mb-2">
        A local-first dataset curation and training preparation tool for AI image models.
      </p>
      <p className="text-[var(--text-secondary)] text-sm leading-relaxed mb-8">
        This wizard will help you configure at least one AI provider so you can start
        generating captions, analyzing images, and building training datasets.
      </p>

      <div className="flex flex-col gap-3 w-full">
        <button
          onClick={onNext}
          className="btn btn-primary flex items-center justify-center gap-2 py-2.5 text-sm font-medium"
        >
          Get Started
          <ArrowRight size={16} />
        </button>
        <button
          onClick={onSkip}
          className="btn btn-secondary flex items-center justify-center gap-1.5 py-2 text-xs text-[var(--text-secondary)]"
        >
          <SkipForward size={13} />
          Skip — I'll configure this later in Settings
        </button>
      </div>
    </div>
  )
}

// ── Step 1: Mode Selection ────────────────────────────────────────────────────

interface ModeCardProps {
  icon: React.ReactNode
  title: string
  subtitle: string
  bullets: string[]
  selected: boolean
  onClick: () => void
}

function ModeCard({ icon, title, subtitle, bullets, selected, onClick }: ModeCardProps) {
  return (
    <button
      onClick={onClick}
      className={`text-left p-4 rounded-xl border-2 transition-all w-full ${
        selected
          ? 'border-[var(--accent)] bg-[var(--accent)]/10'
          : 'border-[var(--border)] bg-[var(--surface)] hover:border-[var(--accent)]/40'
      }`}
    >
      <div className="flex items-start gap-3">
        <div
          className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
            selected ? 'bg-[var(--accent)]/20 text-[var(--accent)]' : 'bg-[var(--border)]/40 text-[var(--text-secondary)]'
          }`}
        >
          {icon}
        </div>
        <div>
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-0.5">{title}</p>
          <p className="text-xs text-[var(--text-secondary)] mb-2">{subtitle}</p>
          <ul className="space-y-0.5">
            {bullets.map((b) => (
              <li key={b} className="text-xs text-[var(--text-secondary)] flex items-center gap-1.5">
                <span className={`w-1 h-1 rounded-full flex-shrink-0 ${selected ? 'bg-[var(--accent)]' : 'bg-[var(--border)]'}`} />
                {b}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </button>
  )
}

function ModeStep({
  mode,
  setMode,
  onNext,
  onBack,
}: {
  mode: WizardMode | null
  setMode: (m: WizardMode) => void
  onNext: () => void
  onBack: () => void
}) {
  return (
    <div className="max-w-xl mx-auto w-full">
      <div className="mb-6">
        <h2 className="text-xl font-bold text-[var(--text-primary)] mb-1">How will you power Draco?</h2>
        <p className="text-sm text-[var(--text-secondary)]">
          You can always add more providers later in Settings.
        </p>
      </div>

      <div className="space-y-3 mb-8">
        <ModeCard
          icon={<Cpu size={18} />}
          title="Local AI"
          subtitle="Use models running on your own hardware via Ollama"
          bullets={['No API costs', 'Runs fully offline', 'Requires GPU (or fast CPU)', 'Setup takes a few minutes']}
          selected={mode === 'local'}
          onClick={() => setMode('local')}
        />
        <ModeCard
          icon={<Globe size={18} />}
          title="API Keys"
          subtitle="Use cloud providers like OpenAI or Gemini"
          bullets={['Ready in seconds', 'No GPU required', 'Pay-per-use', 'Requires internet connection']}
          selected={mode === 'api'}
          onClick={() => setMode('api')}
        />
        <ModeCard
          icon={<Zap size={18} />}
          title="Both"
          subtitle="Configure local models and API keys for maximum flexibility"
          bullets={['Best of both worlds', 'Fallback between providers', 'Recommended for power users']}
          selected={mode === 'both'}
          onClick={() => setMode('both')}
        />
      </div>

      <div className="flex gap-3">
        <button onClick={onBack} className="btn btn-secondary flex items-center gap-1.5 text-sm">
          <ChevronLeft size={14} /> Back
        </button>
        <button
          onClick={onNext}
          disabled={!mode}
          className="btn btn-primary flex items-center gap-1.5 text-sm ml-auto"
        >
          Continue <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}

// ── Ollama Panel ──────────────────────────────────────────────────────────────

function OllamaPanel() {
  const [ollamaStatus, setOllamaStatus] = useState<'idle' | 'checking' | 'ok' | 'error'>('idle')
  const [ollamaModels, setOllamaModels] = useState<string[]>([])
  const [ollamaError, setOllamaError] = useState<string | null>(null)

  async function checkOllama() {
    setOllamaStatus('checking')
    setOllamaError(null)
    try {
      const result = await providersApi.testProvider('caption', 'ollama')
      if (result.ok) {
        setOllamaStatus('ok')
        // Try to load available models
        try {
          const models = await providersApi.captionModels()
          const ollamaList = models.providers?.['ollama']
          if (Array.isArray(ollamaList)) {
            setOllamaModels(
              ollamaList.map((m: unknown) =>
                typeof m === 'string' ? m : (m as { name?: string })?.name ?? String(m)
              )
            )
          }
        } catch {
          // models list is optional
        }
      } else {
        setOllamaStatus('error')
        setOllamaError('Ollama responded but is not ready to serve caption requests yet.')
      }
    } catch (error) {
      setOllamaStatus('error')
      setOllamaError(error instanceof Error ? error.message : 'Failed to reach Ollama.')
    }
  }

  return (
    <div className="rounded-xl border border-[var(--border)] p-4 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <Server size={15} className="text-[var(--accent)]" />
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">Ollama</h3>
        <span className="text-xs text-[var(--text-secondary)] ml-auto">Local model runtime</span>
      </div>

      {/* Connection check */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={checkOllama}
          disabled={ollamaStatus === 'checking'}
          className="btn btn-secondary btn-sm flex items-center gap-1.5"
        >
          {ollamaStatus === 'checking' ? (
            <RefreshCw size={12} className="animate-spin" />
          ) : (
            <RefreshCw size={12} />
          )}
          Test Connection
        </button>
        {ollamaStatus === 'ok' && (
          <span className="flex items-center gap-1 text-xs text-green-400">
            <CheckCircle size={13} /> Ollama is running
          </span>
        )}
        {ollamaStatus === 'error' && (
          <span className="flex items-center gap-1 text-xs text-red-400">
            <XCircle size={13} /> Not reachable
          </span>
        )}
      </div>

      {ollamaStatus === 'error' && (
        <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 mb-4">
          <p className="text-xs text-yellow-300 flex items-start gap-2">
            <AlertTriangle size={13} className="mt-0.5 flex-shrink-0" />
            <span>
              Ollama isn't running or isn't installed. Download it from{' '}
              <span className="font-mono text-yellow-200">ollama.ai</span>, then run{' '}
              <code className="bg-yellow-900/30 px-1 rounded">ollama serve</code> to start it.
            </span>
          </p>
          {ollamaError && (
            <p className="mt-2 text-[11px] text-yellow-200/90">
              Last error: {ollamaError}
            </p>
          )}
        </div>
      )}

      {/* Already-installed models */}
      {ollamaModels.length > 0 && (
        <div className="mb-4">
          <p className="text-xs font-medium text-[var(--text-secondary)] mb-2 uppercase tracking-wide">
            Installed Models
          </p>
          <div className="flex flex-wrap gap-1.5">
            {ollamaModels.map((m) => (
              <span
                key={m}
                className="px-2 py-0.5 rounded-full bg-green-500/10 border border-green-500/20 text-xs text-green-300"
              >
                {m}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Recommended models */}
      <div>
        <p className="text-xs font-medium text-[var(--text-secondary)] mb-2 uppercase tracking-wide flex items-center gap-1.5">
          <Download size={11} />
          Recommended Models
        </p>
        <div className="space-y-2">
          {OLLAMA_MODELS.map((model) => {
            const isInstalled = ollamaModels.some(
              (m) => m.startsWith(model.tag.split(':')[0])
            )
            return (
              <div
                key={model.id}
                className={`flex items-center gap-3 p-2.5 rounded-lg border ${
                  isInstalled
                    ? 'border-green-500/20 bg-green-500/5'
                    : 'border-[var(--border)] bg-[var(--surface)]'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-[var(--text-primary)]">
                      {model.label}
                    </span>
                    {model.recommended && !isInstalled && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--accent)]/15 text-[var(--accent)] border border-[var(--accent)]/20">
                        Recommended
                      </span>
                    )}
                    {isInstalled && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-500/15 text-green-400 border border-green-500/20">
                        Installed
                      </span>
                    )}
                    <span className="text-[10px] text-[var(--text-secondary)] ml-auto">{model.size}</span>
                  </div>
                  <p className="text-[11px] text-[var(--text-secondary)] mt-0.5">{model.description}</p>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <code className="text-[11px] font-mono text-[var(--text-secondary)] bg-[var(--border)]/40 px-2 py-1 rounded">
                    ollama pull {model.tag}
                  </code>
                  <CopyButton text={`ollama pull ${model.tag}`} />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── API Keys Panel ────────────────────────────────────────────────────────────

interface ApiKeyEntryProps {
  label: string
  providerType: string
  providerName: string
  placeholder: string
  hasKey: boolean
  onSaved: () => void
}

function ApiKeyEntry({ label, providerType, providerName, placeholder, hasKey, onSaved }: ApiKeyEntryProps) {
  const [draft, setDraft] = useState('')
  const [show, setShow] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(hasKey)
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
      onSaved()
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save API key')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="p-3 rounded-lg border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-[var(--text-primary)]">{label}</span>
        {saved && (
          <span className="flex items-center gap-1 text-xs text-green-400">
            <CheckCircle size={12} /> Key saved
          </span>
        )}
      </div>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type={show ? 'text' : 'password'}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSave() }}
            placeholder={saved ? '••••••••••••••••' : placeholder}
            className={inputCls}
          />
          <button
            onClick={() => setShow((p) => !p)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            {show ? <EyeOff size={13} /> : <Eye size={13} />}
          </button>
        </div>
        <button
          onClick={handleSave}
          disabled={saving || !draft.trim()}
          className={`btn btn-sm flex items-center gap-1 ${
            saved ? 'btn-secondary text-green-400' : 'btn-secondary'
          }`}
        >
          {saving ? <RefreshCw size={12} className="animate-spin" /> : saved ? <CheckCircle size={12} /> : null}
          {saving ? 'Saving…' : saved ? 'Update' : 'Save'}
        </button>
      </div>
      {error && <p className="text-xs text-red-400 mt-1">{error}</p>}
    </div>
  )
}

function ApiKeysPanel({ onAnyKeySaved }: { onAnyKeySaved: () => void }) {
  const { data: keyStatus } = useQuery({
    queryKey: ['api-key-status'],
    queryFn: () => providersApi.getApiKeyStatus(),
    staleTime: 10_000,
  })

  const status = keyStatus?.status ?? {}

  const providers = [
    { label: 'OpenAI', providerName: 'openai', placeholder: 'sk-…', hint: 'GPT-4V captions' },
    { label: 'Gemini', providerName: 'gemini', placeholder: 'AIza…', hint: 'Gemini Pro Vision' },
  ]

  return (
    <div className="rounded-xl border border-[var(--border)] p-4 mb-4">
      <div className="flex items-center gap-2 mb-1">
        <Key size={15} className="text-[var(--accent)]" />
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">API Keys</h3>
      </div>
      <p className="text-xs text-[var(--text-secondary)] mb-4">
        Keys are encrypted at rest. You only need to configure the providers you plan to use.
      </p>
      <div className="space-y-2">
        {providers.map(({ label, providerName, placeholder, hint }) => (
          <ApiKeyEntry
            key={providerName}
            label={`${label} — ${hint}`}
            providerType="caption"
            providerName={providerName}
            placeholder={placeholder}
            hasKey={!!status[providerName]}
            onSaved={onAnyKeySaved}
          />
        ))}
      </div>
    </div>
  )
}

// ── Step 2: Configure ─────────────────────────────────────────────────────────

function ConfigureStep({
  mode,
  onNext,
  onBack,
}: {
  mode: WizardMode
  onNext: () => void
  onBack: () => void
}) {
  const [, setApiKeySaved] = useState(false)

  const handleApiKeySaved = useCallback(() => {
    setApiKeySaved(true)
  }, [])

  return (
    <div className="max-w-2xl mx-auto w-full">
      <div className="mb-5">
        <h2 className="text-xl font-bold text-[var(--text-primary)] mb-1">
          {mode === 'local' ? 'Set up Local AI' : mode === 'api' ? 'Add API Keys' : 'Configure Providers'}
        </h2>
        <p className="text-sm text-[var(--text-secondary)]">
          {mode === 'local'
            ? 'Install Ollama and pull a vision model to enable local captioning.'
            : mode === 'api'
            ? 'Add at least one API key to enable cloud-powered captioning.'
            : 'Configure both local and cloud providers for maximum flexibility.'}
        </p>
      </div>

      <div className="max-h-[50vh] overflow-y-auto pr-1 space-y-0">
        {(mode === 'local' || mode === 'both') && <OllamaPanel />}
        {(mode === 'api' || mode === 'both') && (
          <ApiKeysPanel onAnyKeySaved={handleApiKeySaved} />
        )}
      </div>

      <div className="flex gap-3 mt-5 pt-4 border-t border-[var(--border)]">
        <button onClick={onBack} className="btn btn-secondary flex items-center gap-1.5 text-sm">
          <ChevronLeft size={14} /> Back
        </button>
        <button
          onClick={onNext}
          className="btn btn-primary flex items-center gap-1.5 text-sm ml-auto"
        >
          Run Health Check <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}

// ── Step 3: Verify ────────────────────────────────────────────────────────────

interface ProviderStatus {
  type: string
  name: string
  ok: boolean
  latency_ms?: number
}

function VerifyStep({
  onFinish,
  onBack,
}: {
  onFinish: () => void
  onBack: () => void
}) {
  const [checked, setChecked] = useState(false)
  const [statuses, setStatuses] = useState<ProviderStatus[]>([])
  const [checking, setChecking] = useState(false)
  const [checkError, setCheckError] = useState<string | null>(null)

  async function runCheck() {
    setChecking(true)
    setCheckError(null)
    try {
      const health = await providersApi.health()
      const results: ProviderStatus[] = []
      for (const [type, providerMap] of Object.entries(health.providers)) {
        if (typeof providerMap === 'object' && providerMap !== null) {
          for (const [name, status] of Object.entries(providerMap as Record<string, { ok?: boolean; latency_ms?: number }>)) {
            results.push({ type, name, ok: !!status?.ok, latency_ms: status?.latency_ms })
          }
        }
      }
      setStatuses(results)
      setChecked(true)
    } catch (error) {
      setStatuses([])
      setChecked(true)
      setCheckError(error instanceof Error ? error.message : 'Provider health check failed.')
    } finally {
      setChecking(false)
    }
  }

  const anyOk = statuses.some((s) => s.ok)

  return (
    <div className="max-w-xl mx-auto w-full">
      <div className="mb-6">
        <h2 className="text-xl font-bold text-[var(--text-primary)] mb-1">Verify Setup</h2>
        <p className="text-sm text-[var(--text-secondary)]">
          Run a quick health check to confirm at least one provider is reachable.
        </p>
      </div>

      {!checked ? (
        <div className="flex flex-col items-center gap-4 py-8">
          <button
            onClick={runCheck}
            disabled={checking}
            className="btn btn-primary flex items-center gap-2 px-6 py-2.5"
          >
            {checking ? (
              <RefreshCw size={16} className="animate-spin" />
            ) : (
              <RefreshCw size={16} />
            )}
            {checking ? 'Checking…' : 'Run Health Check'}
          </button>
          <p className="text-xs text-[var(--text-secondary)]">
            This pings each configured provider to verify connectivity.
          </p>
        </div>
      ) : (
        <div className="mb-6">
          {statuses.length === 0 ? (
            <div className="text-center py-6">
              <XCircle size={32} className="text-red-400 mx-auto mb-3" />
              <p className="text-sm text-[var(--text-secondary)]">
                No providers responded. You can still proceed and configure them later in Settings.
              </p>
              {checkError && (
                <p className="mt-3 text-xs text-red-300">
                  Health check error: {checkError}
                </p>
              )}
              <button
                onClick={runCheck}
                disabled={checking}
                className="btn btn-secondary btn-sm mt-4 inline-flex items-center gap-1.5"
              >
                {checking ? <RefreshCw size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                Retry Health Check
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {statuses.map(({ type, name, ok, latency_ms }) => (
                <div
                  key={`${type}-${name}`}
                  className={`flex items-center justify-between p-3 rounded-lg border ${
                    ok ? 'border-green-500/20 bg-green-500/5' : 'border-[var(--border)] bg-[var(--surface)]'
                  }`}
                >
                  <div>
                    <span className="text-xs font-medium text-[var(--text-primary)] capitalize">
                      {type} / {name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {latency_ms != null && ok && (
                      <span className="text-xs text-[var(--text-secondary)]">{latency_ms}ms</span>
                    )}
                    {ok ? (
                      <CheckCircle size={15} className="text-green-400" />
                    ) : (
                      <XCircle size={15} className="text-red-400" />
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {anyOk && (
            <div className="mt-4 p-3 rounded-lg bg-green-500/10 border border-green-500/20 flex items-center gap-2">
              <CheckCircle size={16} className="text-green-400 flex-shrink-0" />
              <p className="text-sm text-green-300">
                You're all set! At least one provider is ready to use.
              </p>
            </div>
          )}

          {!anyOk && statuses.length > 0 && (
            <div className="mt-4 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20 flex items-start gap-2">
              <AlertTriangle size={15} className="text-yellow-400 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-yellow-300">
                No providers are reachable right now. You can still enter the app and configure
                them later from the Settings page.
              </p>
            </div>
          )}
        </div>
      )}

      <div className="flex gap-3 pt-4 border-t border-[var(--border)]">
        <button onClick={onBack} className="btn btn-secondary flex items-center gap-1.5 text-sm">
          <ChevronLeft size={14} /> Back
        </button>
        <button
          onClick={onFinish}
          className="btn btn-primary flex items-center gap-1.5 text-sm ml-auto"
          disabled={!checked && !checking}
        >
          {anyOk ? (
            <>
              Enter Draco <ArrowRight size={14} />
            </>
          ) : checked ? (
            <>
              Enter Anyway <ArrowRight size={14} />
            </>
          ) : (
            'Check First'
          )}
        </button>
      </div>
    </div>
  )
}

// ── Progress indicator ────────────────────────────────────────────────────────

const STEP_LABELS = ['Welcome', 'Mode', 'Configure', 'Verify']

function StepIndicator({ currentStep }: { currentStep: number }) {
  return (
    <div className="flex items-center gap-2 justify-center mb-10">
      {STEP_LABELS.map((label, i) => (
        <React.Fragment key={label}>
          <div className="flex flex-col items-center gap-1">
            <div
              className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all ${
                i < currentStep
                  ? 'bg-[var(--accent)] border-[var(--accent)] text-white'
                  : i === currentStep
                  ? 'border-[var(--accent)] text-[var(--accent)] bg-transparent'
                  : 'border-[var(--border)] text-[var(--text-secondary)] bg-transparent'
              }`}
            >
              {i < currentStep ? <Check size={13} /> : i + 1}
            </div>
            <span
              className={`text-[10px] font-medium ${
                i === currentStep ? 'text-[var(--accent)]' : 'text-[var(--text-secondary)]'
              }`}
            >
              {label}
            </span>
          </div>
          {i < STEP_LABELS.length - 1 && (
            <div
              className={`flex-1 h-px max-w-12 mb-5 transition-colors ${
                i < currentStep ? 'bg-[var(--accent)]' : 'bg-[var(--border)]'
              }`}
            />
          )}
        </React.Fragment>
      ))}
    </div>
  )
}

// ── Main Setup Component ──────────────────────────────────────────────────────

export function Setup() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [mode, setMode] = useState<WizardMode | null>(null)
  const projects = useProjectStore((state) => state.projects)

  function skip() {
    completeSetup()
    navigate(projects.length > 0 ? '/gallery' : '/settings', { replace: true })
  }

  function finish() {
    completeSetup()
    navigate(projects.length > 0 ? '/gallery' : '/settings', { replace: true })
  }

  function goTo(s: number) {
    setStep(s)
  }

  return (
    <div className="min-h-screen bg-[var(--background)] flex flex-col items-center justify-center px-4 py-10">
      {/* Logo / branding strip */}
      <div className="w-full max-w-2xl mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-[var(--accent)]/20 border border-[var(--accent)]/30 flex items-center justify-center">
            <Layers size={15} className="text-[var(--accent)]" />
          </div>
          <span className="text-sm font-semibold text-[var(--text-primary)]">Draco Studio</span>
        </div>
        {step > 0 && (
          <button
            onClick={skip}
            className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors flex items-center gap-1"
          >
            <SkipForward size={12} /> Skip setup
          </button>
        )}
      </div>

      {/* Card */}
      <div className="w-full max-w-2xl bg-[var(--surface)] rounded-2xl border border-[var(--border)] p-8 shadow-xl">
        {step > 0 && <StepIndicator currentStep={step - 1} />}

        {step === 0 && <WelcomeStep onNext={() => goTo(1)} onSkip={skip} />}

        {step === 1 && (
          <ModeStep
            mode={mode}
            setMode={setMode}
            onNext={() => goTo(2)}
            onBack={() => goTo(0)}
          />
        )}

        {step === 2 && mode && (
          <ConfigureStep
            mode={mode}
            onNext={() => goTo(3)}
            onBack={() => goTo(1)}
          />
        )}

        {step === 3 && (
          <VerifyStep
            onFinish={finish}
            onBack={() => goTo(2)}
          />
        )}
      </div>

      <p className="mt-4 text-xs text-[var(--text-secondary)]">
        All configuration is stored locally. Nothing is sent to Draco servers.
      </p>
    </div>
  )
}
