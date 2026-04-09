import { useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { AlertTriangle, RefreshCw, ServerCrash } from 'lucide-react'
import { AppShell } from '@/components/layout/AppShell'
import { ThemeProvider } from '@/components/providers/ThemeProvider'
import { ToastProvider } from '@/components/providers/ToastProvider'
import { Dashboard } from '@/views/Dashboard'
import { Gallery } from '@/views/Gallery'
import { Captions } from '@/views/Captions'
import { Faces } from '@/views/Faces'
import { Ranking } from '@/views/Ranking'
import Coach from '@/views/Coach'
import Augmentation from '@/views/Augmentation'
import Export from '@/views/Export'
import Settings from '@/views/Settings'
import Benchmark from '@/views/Benchmark'
import { Duplicates } from '@/views/Duplicates'
import Search from '@/views/Search'
import { AutoSort } from '@/views/AutoSort'
import { Setup } from '@/views/Setup'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import api, { jobsApi, projectsApi } from '@/hooks/useApi'
import { useJobStore } from '@/stores/useJobStore'
import { useProjectStore } from '@/stores/useProjectStore'
import type { Job } from '@/types/api'
import { useToast } from '@/components/providers/ToastProvider'
import { shouldRetryRequest } from '@/lib/queryRetry'

function isSetupComplete(): boolean {
  try {
    return localStorage.getItem('draco_setup_complete') === '1'
  } catch {
    return true // storage unavailable; do not block the app
  }
}

function ProjectBootstrap() {
  const setProjects = useProjectStore((s) => s.setProjects)
  const toast = useToast()
  const lastErrorRef = useRef<string | null>(null)

  const { data, error } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    staleTime: 30_000,
    refetchInterval: 30_000,
  })

  useEffect(() => {
    if (data) setProjects(data)
  }, [data, setProjects])

  useEffect(() => {
    const message = error instanceof Error ? error.message : null
    if (!message || message === lastErrorRef.current) return
    lastErrorRef.current = message
    toast.error(`Failed to load projects: ${message}`)
  }, [error, toast])

  return null
}

function StartupGuard({ children }: { children: React.ReactNode }) {
  const {
    data,
    error,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['startup-health'],
    queryFn: () => api.get<{ status: string; database: boolean; version: string }>('/api/health').then((response) => response.data),
    staleTime: 10_000,
    retry: shouldRetryRequest,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),
    refetchOnWindowFocus: false,
  })

  if (isLoading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[var(--background)] px-4 text-[var(--text-secondary)]">
        <RefreshCw size={28} className="animate-spin text-[var(--accent)]" />
        <div className="text-center">
          <p className="text-base font-medium text-[var(--text-primary)]">Connecting to Draco backend</p>
          <p className="mt-1 text-sm">Starting services and checking local storage access...</p>
        </div>
      </div>
    )
  }

  if (error || !data || data.status !== 'ok' || !data.database) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-[var(--background)] px-4 text-[var(--text-secondary)]">
        <ServerCrash size={36} className="text-red-400" />
        <div className="max-w-xl text-center">
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">Draco could not finish startup</h1>
          <p className="mt-2 text-sm">
            {error instanceof Error
              ? error.message
              : 'The backend is reachable but not healthy enough to use safely.'}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 text-sm max-w-xl w-full">
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} className="mt-0.5 text-yellow-400" />
            <div>
              <p className="font-medium text-[var(--text-primary)]">What to check</p>
              <p className="mt-1">Make sure the FastAPI backend is running, the database is writable, and local provider startup did not fail.</p>
              {data && (
                <p className="mt-2 text-xs text-[var(--text-secondary)]">
                  Backend status: {data.status} · Database: {data.database ? 'ok' : 'unavailable'} · Version: {data.version}
                </p>
              )}
            </div>
          </div>
        </div>
        <button onClick={() => refetch()} className="btn btn-primary" disabled={isFetching}>
          {isFetching ? <RefreshCw size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Retry Startup Check
        </button>
      </div>
    )
  }

  return <>{children}</>
}

function invalidateQueriesForJobCompletion(queryClient: QueryClient, job: Job) {
  queryClient.invalidateQueries({ queryKey: ['jobs-poll'] })

  if (job.type === 'duplicate_scan') {
    queryClient.invalidateQueries({ queryKey: ['duplicates'] })
    return
  }

  if (job.type === 'augmentation') {
    queryClient.invalidateQueries({ queryKey: ['augmentation-pending'] })
    queryClient.invalidateQueries({ queryKey: ['assets'] })
    queryClient.invalidateQueries({ queryKey: ['project-stats'] })
    return
  }

  if (job.type === 'face_clustering') {
    queryClient.invalidateQueries({ queryKey: ['face-clusters'] })
    queryClient.invalidateQueries({ queryKey: ['cluster-assets'] })
    return
  }

  if (job.type === 'caption' || job.type === 'export_sidecars') {
    queryClient.invalidateQueries({ queryKey: ['caption-assets'] })
    queryClient.invalidateQueries({ queryKey: ['captions'] })
    return
  }

  if (job.type.startsWith('export_')) {
    queryClient.invalidateQueries({ queryKey: ['export-validation'] })
    return
  }

  if (job.type === 'analysis' || job.type === 'ai_judge') {
    queryClient.invalidateQueries({ queryKey: ['assets'] })
    queryClient.invalidateQueries({ queryKey: ['project-stats'] })
    return
  }

  if (job.type === 'ingest_upload' || job.type === 'ingest_directory' || job.type === 'generic') {
    queryClient.invalidateQueries({ queryKey: ['projects'] })
    queryClient.invalidateQueries({ queryKey: ['assets'] })
    queryClient.invalidateQueries({ queryKey: ['project-stats'] })
  }
}

function formatJobLabel(job: Job): string {
  const labels: Record<string, string> = {
    duplicate_scan: 'Duplicate scan',
    face_clustering: 'Face clustering',
    augmentation: 'Augmentation',
    ingest_upload: 'Import',
    ingest_directory: 'Directory import',
    analysis: 'Analysis',
    caption: 'Caption generation',
    export_sidecars: 'Sidecar export',
    ai_judge: 'AI judge',
    export_lora: 'LoRA export',
    export_kohya: 'Kohya export',
    export_zip: 'ZIP export',
    generic: 'Background job',
  }

  return labels[job.type] ?? job.type.replaceAll('_', ' ')
}

function shouldToastJobSuccess(job: Job): boolean {
  return [
    'duplicate_scan',
    'face_clustering',
    'augmentation',
    'ingest_upload',
    'ingest_directory',
    'analysis',
    'caption',
    'export_sidecars',
    'ai_judge',
    'export_lora',
    'export_kohya',
    'export_zip',
  ].includes(job.type)
}

function formatJobSuccessMessage(job: Job): string {
  const label = formatJobLabel(job)
  if (job.type.startsWith('export_')) {
    return `${label} finished successfully.`
  }
  if (job.progress >= 100) {
    return `${label} complete.`
  }
  return `${label} finished.`
}

function JobPoller() {
  const setJobs = useJobStore((s) => s.setJobs)
  const activeJobIds = useJobStore((s) => s.activeJobIds)
  const queryClient = useQueryClient()
  const toast = useToast()
  const previousJobsRef = useRef<Record<string, Job>>({})
  const lastPollErrorRef = useRef<string | null>(null)

  // Poll fast (2s) when jobs are active, slow (15s) when idle
  const hasActiveJobs = activeJobIds.length > 0
  const pollInterval = hasActiveJobs ? 2000 : 15000

  const { data, error } = useQuery({
    queryKey: ['jobs-poll'],
    queryFn: jobsApi.list,
    refetchInterval: pollInterval,
  })

  useEffect(() => {
    if (!data) return

    const previousJobs = previousJobsRef.current
    for (const job of data) {
      const previous = previousJobs[job.id]
      if (!previous || previous.status === job.status) continue
      if (job.status === 'done' || job.status === 'failed' || job.status === 'cancelled') {
        invalidateQueriesForJobCompletion(queryClient, job)
      }
      if (job.status === 'done' && shouldToastJobSuccess(job)) {
        toast.success(formatJobSuccessMessage(job))
      }
      if (job.status === 'failed') {
        const label = formatJobLabel(job)
        const errorMessage = job.error?.trim()
        if (errorMessage?.toLowerCase().includes('interrupted by application restart')) {
          toast.warning(`${label} stopped when Draco restarted. You can retry it safely.`)
        } else {
          toast.error(errorMessage ? `${label} failed: ${errorMessage}` : `${label} failed`)
        }
      }
      if (job.status === 'cancelled') {
        toast.info(`${formatJobLabel(job)} cancelled`)
      }
    }

    setJobs(data)
    previousJobsRef.current = Object.fromEntries(data.map((job) => [job.id, job]))
  }, [data, queryClient, setJobs, toast])

  useEffect(() => {
    const message = error instanceof Error ? error.message : null
    if (!message || message === lastPollErrorRef.current) return
    lastPollErrorRef.current = message
    toast.warning(`Failed to refresh job status: ${message}`)
  }, [error, toast])

  return null
}

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <StartupGuard>
          <BrowserRouter>
            <ProjectBootstrap />
            <JobPoller />
            <ErrorBoundary>
              <Routes>
                <Route path="/setup" element={<Setup />} />
                <Route path="/" element={isSetupComplete() ? <AppShell /> : <Navigate to="/setup" replace />}>
                  <Route index element={<Navigate to="/gallery" replace />} />
                  <Route path="dashboard" element={<Dashboard />} />
                  <Route path="gallery" element={<Gallery />} />
                  <Route path="captions" element={<Captions />} />
                  <Route path="faces" element={<Faces />} />
                  <Route path="ranking" element={<Ranking />} />
                  <Route path="coach" element={<Coach />} />
                  <Route path="augmentation" element={<Augmentation />} />
                  <Route path="export" element={<Export />} />
                  <Route path="settings" element={<Settings />} />
                  <Route path="benchmark" element={<Benchmark />} />
                  <Route path="duplicates" element={<Duplicates />} />
                  <Route path="search" element={<Search />} />
                  <Route path="autosort" element={<AutoSort />} />
                </Route>
              </Routes>
            </ErrorBoundary>
          </BrowserRouter>
        </StartupGuard>
      </ToastProvider>
    </ThemeProvider>
  )
}
