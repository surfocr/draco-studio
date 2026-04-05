// frontend/src/views/Benchmark.tsx
// Provider bakeoff/benchmark panel — compare caption providers on a sample

import React, { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useProjectStore } from '@/stores/useProjectStore'
import { useJobStore } from '@/stores/useJobStore'
import api from '@/hooks/useApi'
import { Cpu, Play, Check, Clock, ChevronDown, ChevronUp } from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartTooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { clsx } from 'clsx'
import { assetsApi } from '@/hooks/useApi'

interface ProviderResult {
  provider: string
  latency_ms_avg: number
  latency_ms_p95: number
  success_rate: number
  error_count: number
  sample_outputs: Array<{ asset: string; text: string }>
  error?: string
}

const PROVIDER_TYPE_OPTIONS = [
  { value: 'caption', label: 'Caption Providers' },
  { value: 'face', label: 'Face Detection' },
  { value: 'embedding', label: 'Embedding' },
]

export default function Benchmark() {
  const activeProject = useProjectStore((s) => s.activeProject)
  const jobs = useJobStore((s) => s.jobs)

  const [providerType, setProviderType] = useState('caption')
  const [selectedProviders, setSelectedProviders] = useState<Set<string>>(new Set())
  const [results, setResults] = useState<ProviderResult[] | null>(null)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null)

  // Load available providers for selected type
  const { data: providersData } = useQuery({
    queryKey: ['benchmark-providers', providerType],
    queryFn: () =>
      api
        .get<{ providers: string[] }>(`/api/benchmark/providers/${providerType}`)
        .then((r) => r.data),
  })

  // Load sample assets for this project
  const { data: assetsData } = useQuery({
    queryKey: ['benchmark-assets', activeProject?.id],
    queryFn: () =>
      assetsApi.list(activeProject!.id, {
        page: 1,
        page_size: 10,
        sort_by: 'composite_score',
        sort_dir: 'desc',
      }),
    enabled: !!activeProject?.id,
  })

  // Watch job for completion
  const activeJob = activeJobId ? jobs.find((j) => j.id === activeJobId) : null
  useEffect(() => {
    if (activeJob?.status === 'completed' && activeJob.result) {
      setResults(activeJob.result as ProviderResult[])
      setActiveJobId(null)
    }
  }, [activeJob])

  const runMutation = useMutation({
    mutationFn: () =>
      api
        .post<{ job_id: string }>('/api/benchmark/run', {
          provider_type: providerType,
          provider_names: Array.from(selectedProviders),
          asset_ids: assetsData?.items?.map((a) => a.id) ?? [],
        })
        .then((r) => r.data),
    onSuccess: (data) => setActiveJobId(data.job_id),
  })

  const providers = providersData?.providers ?? []
  const sampleAssets = assetsData?.items ?? []
  const isRunning = !!activeJobId && activeJob?.status === 'running'

  const toggleProvider = (name: string) => {
    setSelectedProviders((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const latencyData =
    results?.map((r) => ({
      name: r.provider,
      avg: Math.round(r.latency_ms_avg),
      p95: Math.round(r.latency_ms_p95),
    })) ?? []

  const successData =
    results?.map((r) => ({
      name: r.provider,
      rate: Math.round(r.success_rate * 100),
    })) ?? []

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border flex items-center gap-3 flex-shrink-0">
        <Cpu className="text-accent" size={20} />
        <h1 className="text-lg font-semibold text-text-primary">Provider Benchmark</h1>
        <span className="text-xs text-text-secondary">Compare providers on your dataset</span>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Config panel */}
        <div className="card p-5 space-y-4">
          <h2 className="text-sm font-semibold text-text-primary">Benchmark Configuration</h2>

          {/* Provider type */}
          <div>
            <label className="block text-xs text-text-secondary mb-2">Provider Type</label>
            <div className="flex gap-2">
              {PROVIDER_TYPE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => {
                    setProviderType(opt.value)
                    setSelectedProviders(new Set())
                  }}
                  className={clsx(
                    'px-3 py-1.5 rounded text-sm font-medium transition-colors',
                    providerType === opt.value
                      ? 'bg-accent text-white'
                      : 'bg-surface-elevated text-text-secondary hover:text-text-primary'
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Provider selection */}
          <div>
            <label className="block text-xs text-text-secondary mb-2">
              Select Providers to Compare
            </label>
            <div className="flex flex-wrap gap-2">
              {providers.length === 0 ? (
                <p className="text-xs text-text-secondary">
                  No providers registered for this type.
                </p>
              ) : (
                providers.map((name) => (
                  <button
                    key={name}
                    onClick={() => toggleProvider(name)}
                    className={clsx(
                      'px-3 py-1.5 rounded-lg text-sm border transition-colors',
                      selectedProviders.has(name)
                        ? 'border-accent bg-accent/10 text-accent'
                        : 'border-border text-text-secondary hover:border-text-secondary'
                    )}
                  >
                    {name}
                  </button>
                ))
              )}
            </div>
          </div>

          {/* Sample preview */}
          <div>
            <label className="block text-xs text-text-secondary mb-2">
              Sample Images ({sampleAssets.length} highest-scored)
            </label>
            <div className="flex gap-2 overflow-x-auto pb-1">
              {sampleAssets.map((a) => (
                <img
                  key={a.id}
                  src={assetsApi.thumbnailUrl(a.id, 128)}
                  alt={a.filename}
                  className="w-12 h-12 rounded object-cover flex-shrink-0 border border-border bg-surface-elevated"
                />
              ))}
            </div>
          </div>

          {/* Run button */}
          <div className="space-y-1">
            <button
              onClick={() => runMutation.mutate()}
              disabled={selectedProviders.size < 2 || sampleAssets.length === 0 || isRunning}
              className={clsx(
                'flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-colors',
                selectedProviders.size >= 2 && !isRunning
                  ? 'bg-accent text-white hover:bg-accent/90'
                  : 'bg-surface-elevated text-text-secondary cursor-not-allowed'
              )}
            >
              {isRunning ? (
                <>
                  <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                  Running... {activeJob?.progress ?? 0}%
                </>
              ) : (
                <>
                  <Play size={14} /> Run Benchmark
                </>
              )}
            </button>
            {selectedProviders.size < 2 && (
              <p className="text-xs text-text-secondary">Select at least 2 providers to compare.</p>
            )}
          </div>
        </div>

        {/* Results */}
        {results && (
          <div className="space-y-4">
            <h2 className="text-sm font-semibold text-text-primary">Results</h2>

            {/* Latency chart */}
            <div className="card p-5">
              <h3 className="text-xs font-medium text-text-secondary mb-4 uppercase tracking-wide">
                Latency (ms)
              </h3>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={latencyData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                  <XAxis dataKey="name" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
                  <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
                  <RechartTooltip
                    contentStyle={{
                      background: 'var(--surface-elevated)',
                      border: '1px solid var(--border)',
                      borderRadius: 8,
                    }}
                    labelStyle={{ color: 'var(--text-primary)' }}
                    itemStyle={{ color: 'var(--text-secondary)' }}
                  />
                  <Bar dataKey="avg" name="Avg" fill="var(--accent)" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="p95" name="P95" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <div className="flex gap-4 mt-2 justify-center">
                <div className="flex items-center gap-1.5 text-xs text-text-secondary">
                  <div className="w-3 h-3 rounded bg-accent" /> Average
                </div>
                <div className="flex items-center gap-1.5 text-xs text-text-secondary">
                  <div className="w-3 h-3 rounded bg-yellow-500" /> P95
                </div>
              </div>
            </div>

            {/* Success rate */}
            <div className="card p-5">
              <h3 className="text-xs font-medium text-text-secondary mb-4 uppercase tracking-wide">
                Success Rate (%)
              </h3>
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={successData}>
                  <XAxis dataKey="name" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                  />
                  <RechartTooltip
                    contentStyle={{
                      background: 'var(--surface-elevated)',
                      border: '1px solid var(--border)',
                      borderRadius: 8,
                    }}
                  />
                  <Bar dataKey="rate" name="Success %" radius={[4, 4, 0, 0]}>
                    {successData.map((entry, i) => (
                      <Cell
                        key={i}
                        fill={
                          entry.rate >= 90
                            ? '#22c55e'
                            : entry.rate >= 70
                              ? '#f59e0b'
                              : '#ef4444'
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Per-provider details */}
            <div className="space-y-3">
              {results.map((r) => (
                <div
                  key={r.provider}
                  className="card overflow-hidden"
                >
                  <button
                    className="w-full flex items-center justify-between p-4 hover:bg-surface-elevated transition-colors"
                    onClick={() =>
                      setExpandedProvider(expandedProvider === r.provider ? null : r.provider)
                    }
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className={clsx(
                          'w-2 h-2 rounded-full',
                          r.error
                            ? 'bg-red-500'
                            : r.success_rate >= 0.9
                              ? 'bg-green-500'
                              : 'bg-yellow-500'
                        )}
                      />
                      <span className="font-medium text-text-primary text-sm">{r.provider}</span>
                      {r.error && <span className="text-xs text-red-400">{r.error}</span>}
                    </div>
                    <div className="flex items-center gap-6 text-xs text-text-secondary">
                      {!r.error && (
                        <>
                          <span className="flex items-center gap-1">
                            <Clock size={11} /> {Math.round(r.latency_ms_avg)}ms avg
                          </span>
                          <span className="flex items-center gap-1">
                            <Check size={11} /> {Math.round(r.success_rate * 100)}%
                          </span>
                        </>
                      )}
                      {expandedProvider === r.provider ? (
                        <ChevronUp size={14} />
                      ) : (
                        <ChevronDown size={14} />
                      )}
                    </div>
                  </button>

                  {expandedProvider === r.provider && !r.error && r.sample_outputs?.length > 0 && (
                    <div className="border-t border-border p-4 space-y-3">
                      <p className="text-xs font-medium text-text-secondary uppercase tracking-wide">
                        Sample Outputs
                      </p>
                      {r.sample_outputs.map((out, i) => (
                        <div key={i} className="bg-surface-elevated rounded-lg p-3">
                          <p className="text-xs text-text-secondary mb-1">
                            Asset {out.asset.slice(0, 8)}...
                          </p>
                          <p className="text-sm text-text-primary">{out.text}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
