/**
 * Typed API client.
 * All backend endpoints in one place with proper error handling.
 */
import axios from 'axios'
import type {
  AIJudgeComparisonResult,
  AIJudgeResult,
  AssetDetail,
  AssetFilters,
  AssetListResponse,
  AssetSummary,
  AssetUpdate,
  AugmentationPlan,
  AugmentationResult,
  CaptionConsistencyReport,
  CaptionVersion,
  CoachReport,
  ExportJob,
  ExportValidation,
  Job,
  LeaderboardEntry,
  Project,
  ProjectCreate,
  ProviderHealthMap,
  RankingAssetPair,
  RankingSession,
  SortDir,
  SortField,
} from '@/types/api'

const BASE_URL = import.meta.env.VITE_API_URL ?? ''

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

// ── Projects ──────────────────────────────────────────────────────────────────

export const projectsApi = {
  list: () => api.get<Project[]>('/api/projects').then((r) => r.data),

  get: (id: string) =>
    api.get<Project>(`/api/projects/${id}`).then((r) => r.data),

  create: (data: ProjectCreate) =>
    api.post<Project>('/api/projects', data).then((r) => r.data),

  update: (id: string, data: Partial<ProjectCreate>) =>
    api.patch<Project>(`/api/projects/${id}`, data).then((r) => r.data),

  delete: (id: string) => api.delete(`/api/projects/${id}`),

  stats: (id: string) =>
    api.get<Record<string, number>>(`/api/projects/${id}/stats`).then((r) => r.data),
}

// ── Assets ────────────────────────────────────────────────────────────────────

export const assetsApi = {
  list: (
    projectId: string,
    params: {
      page?: number
      page_size?: number
      sort_by?: SortField
      sort_dir?: SortDir
    } & AssetFilters
  ) =>
    api
      .get<AssetListResponse>(`/api/projects/${projectId}/assets`, { params })
      .then((r) => r.data),

  get: (id: string) =>
    api.get<AssetDetail>(`/api/assets/${id}`).then((r) => r.data),

  update: (id: string, data: AssetUpdate) =>
    api.patch<AssetSummary>(`/api/assets/${id}`, data).then((r) => r.data),

  delete: (id: string) => api.delete(`/api/assets/${id}`),

  reanalyze: (id: string) =>
    api.post<{ job_id: string }>(`/api/assets/${id}/reanalyze`).then((r) => r.data),

  thumbnailUrl: (id: string, size: 512 | 128 = 512) =>
    `${BASE_URL}/api/assets/${id}/thumbnail?size=${size}`,

  originalUrl: (id: string) => `${BASE_URL}/api/assets/${id}/original`,

  ingestUpload: (projectId: string, files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return api
      .post<{ job_id: string; file_count: number }>(
        `/api/projects/${projectId}/assets/ingest`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300_000 }
      )
      .then((r) => r.data)
  },

  ingestDirectory: (projectId: string, directoryPath: string, recursive = true) =>
    api
      .post<{ job_id: string }>(`/api/projects/${projectId}/assets/ingest-directory`, {
        directory_path: directoryPath,
        recursive,
      })
      .then((r) => r.data),

  bulkAction: (
    projectId: string,
    action: string,
    assetIds: string[]
  ) => {
    const form = new FormData()
    form.append('action', action)
    assetIds.forEach((id) => form.append('asset_ids', id))
    return api
      .post<{ affected: number; action: string }>(
        `/api/projects/${projectId}/assets/bulk-action`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      .then((r) => r.data)
  },
}

// ── Captions ──────────────────────────────────────────────────────────────────

export const captionsApi = {
  list: (assetId: string) =>
    api.get<CaptionVersion[]>(`/api/assets/${assetId}/captions`).then((r) => r.data),

  generate: (assetId: string, provider: string, style: string, options?: Record<string, unknown>) =>
    api
      .post<CaptionVersion>(`/api/assets/${assetId}/captions/generate`, { provider, style, options })
      .then((r) => r.data),

  compare: (assetId: string, providers: string[], style: string) =>
    api
      .post<CaptionVersion[]>(`/api/assets/${assetId}/captions/compare`, { providers, style })
      .then((r) => r.data),

  activate: (versionId: string) =>
    api.put<{ ok: boolean; asset_id: string }>(`/api/captions/${versionId}/activate`).then((r) => r.data),

  edit: (versionId: string, text: string, author = 'human') =>
    api.post<CaptionVersion>(`/api/captions/${versionId}/edit`, { text, author }).then((r) => r.data),

  delete: (versionId: string) =>
    api.delete(`/api/captions/${versionId}`),

  // Legacy compat
  update: (captionId: string, text: string) =>
    api.patch<CaptionVersion>(`/api/captions/${captionId}`, { text }).then((r) => r.data),

  bulkGenerate: (
    projectId: string,
    assetIds: string[],
    provider: string,
    style: string,
    options?: Record<string, unknown>
  ) =>
    api
      .post<{ job_id: string; asset_count: number }>(`/api/projects/${projectId}/captions/bulk`, {
        asset_ids: assetIds,
        provider,
        style,
        options,
      })
      .then((r) => r.data),

  bulkEdit: (
    projectId: string,
    assetIds: string[],
    operation: 'prepend' | 'append' | 'find_replace' | 'normalize',
    opts: { text?: string; find?: string; replace?: string; use_regex?: boolean }
  ) =>
    api
      .post<{ operation: string; modified: number }>(`/api/projects/${projectId}/captions/bulk-edit`, {
        asset_ids: assetIds,
        operation,
        ...opts,
      })
      .then((r) => r.data),

  exportSidecars: (projectId: string, assetIds?: string[], outputDir?: string) =>
    api
      .post<{ job_id: string; asset_count: number }>(`/api/projects/${projectId}/captions/export`, {
        asset_ids: assetIds ?? null,
        output_dir: outputDir ?? null,
      })
      .then((r) => r.data),

  consistency: (projectId: string, triggerWords?: string) =>
    api
      .get<CaptionConsistencyReport>(`/api/projects/${projectId}/captions/consistency`, {
        params: triggerWords ? { trigger_words: triggerWords } : undefined,
      })
      .then((r) => r.data),
}

// ── Jobs ──────────────────────────────────────────────────────────────────────

export const jobsApi = {
  list: () => api.get<Job[]>('/api/jobs').then((r) => r.data),
  get: (id: string) => api.get<Job>(`/api/jobs/${id}`).then((r) => r.data),
  cancel: (id: string) => api.delete(`/api/jobs/${id}`),
}

// ── Providers (enhanced) ──────────────────────────────────────────────────────

export const providersApi = {
  health: () =>
    api.get<ProviderHealthMap>('/api/providers/health').then((r) => r.data),

  list: () =>
    api.get<{ providers: Record<string, string[]> }>('/api/providers').then((r) => r.data),

  listByType: (type: string) =>
    api.get<{ type: string; providers: string[] }>(`/api/providers/${type}`).then((r) => r.data),

  testProvider: (type: string, name: string) =>
    api
      .post<{ ok: boolean; latency_ms: number; details: unknown }>(
        `/api/providers/${type}/${name}/test`
      )
      .then((r) => r.data),

  captionModels: () =>
    api
      .get<{ providers: Record<string, unknown[]> }>('/api/providers/caption/models')
      .then((r) => r.data),

  saveApiKey: (providerType: string, providerName: string, apiKey: string) =>
    api
      .post<{ status: string; provider_name: string }>('/api/providers/api-key', {
        provider_type: providerType,
        provider_name: providerName,
        api_key: apiKey,
      })
      .then((r) => r.data),

  getApiKeyStatus: () =>
    api
      .get<{ status: Record<string, boolean> }>('/api/providers/api-key-status')
      .then((r) => r.data),
}

// ── Coach (enhanced) ──────────────────────────────────────────────────────────

export const coachApi = {
  analyze: (projectId: string, triggerWords?: string) =>
    api
      .get<CoachReport>(`/api/projects/${projectId}/coach/analyze`, {
        params: triggerWords ? { trigger_words: triggerWords } : undefined,
      })
      .then((r) => r.data),

  report: (projectId: string) =>
    api.get<CoachReport>(`/api/projects/${projectId}/coach/report`).then((r) => r.data),

  applyAction: (projectId: string, action: string, assetIds: string[]) =>
    api
      .post<{ affected: number; action: string }>(
        `/api/projects/${projectId}/coach/apply/${action}`,
        { asset_ids: assetIds }
      )
      .then((r) => r.data),

  removeCandidates: (projectId: string, page = 1, pageSize = 20) =>
    api
      .get<{ items: AssetSummary[]; total: number }>(
        `/api/projects/${projectId}/coach/remove-candidates`,
        { params: { page, page_size: pageSize } }
      )
      .then((r) => r.data),
}

// ── Augmentation ──────────────────────────────────────────────────────────────

export const augmentationApi = {
  getPlan: (projectId: string) =>
    api
      .get<{ project_id: string; plans: AugmentationPlan[] }>(
        `/api/projects/${projectId}/augmentation/plan`
      )
      .then((r) => r.data),

  outpaint: (
    assetId: string,
    targetWidth: number,
    targetHeight: number,
    provider = 'auto',
    prompt?: string
  ) =>
    api
      .post<{
        result_id: string
        status: string
        output_path: string
        operation: string
        provider: string
        error: string | null
      }>(`/api/assets/${assetId}/outpaint`, {
        target_width: targetWidth,
        target_height: targetHeight,
        provider,
        prompt,
      })
      .then((r) => r.data),

  autoFit: (
    projectId: string,
    assetIds: string[],
    targetWidth: number,
    targetHeight: number
  ) =>
    api
      .post<{ job_id: string; asset_count: number }>(
        `/api/projects/${projectId}/augmentation/auto-fit`,
        { asset_ids: assetIds, target_width: targetWidth, target_height: targetHeight }
      )
      .then((r) => r.data),

  getResult: (resultId: string) =>
    api.get<AugmentationResult>(`/api/augmentation/results/${resultId}`).then((r) => r.data),

  approveResult: (resultId: string) =>
    api
      .post<{ status: string; new_asset_id: string }>(
        `/api/augmentation/results/${resultId}/approve`
      )
      .then((r) => r.data),

  rejectResult: (resultId: string) =>
    api.post(`/api/augmentation/results/${resultId}/reject`).then((r) => r.data),

  listPending: () =>
    api.get<{ results: AugmentationResult[] }>('/api/augmentation/results').then((r) => r.data),
}

// ── Export (enhanced) ─────────────────────────────────────────────────────────

export const exportApi = {
  createLora: (
    projectId: string,
    config: {
      trigger_word: string
      repeats?: number
      caption_style?: string
      include_only_captioned?: boolean
      include_only_approved?: boolean
      min_score?: number | null
      max_images?: number | null
      image_format?: string
      create_zip?: boolean
      dataset_name?: string
    }
  ) =>
    api
      .post<{ export_job_id: string; job_id: string; asset_count: number }>(
        `/api/projects/${projectId}/export/lora`,
        config
      )
      .then((r) => r.data),

  createKohya: (
    projectId: string,
    config: {
      trigger_word: string
      repeats?: number
      dataset_name?: string
      model_type?: string
      learning_rate?: number
      epochs?: number
      batch_size?: number
      network_rank?: number
      network_alpha?: number
      generate_train_script?: boolean
      create_zip?: boolean
    }
  ) =>
    api
      .post<{ export_job_id: string; job_id: string; asset_count: number }>(
        `/api/projects/${projectId}/export/kohya`,
        config
      )
      .then((r) => r.data),

  createZip: (
    projectId: string,
    config: {
      dataset_name?: string
      include_metadata?: boolean
      asset_ids?: string[]
    }
  ) =>
    api
      .post<{ export_job_id: string; job_id: string; asset_count: number }>(
        `/api/projects/${projectId}/export/zip`,
        config
      )
      .then((r) => r.data),

  getJob: (exportJobId: string) =>
    api.get<ExportJob>(`/api/export/jobs/${exportJobId}`).then((r) => r.data),

  downloadUrl: (exportJobId: string) =>
    `${BASE_URL}/api/export/jobs/${exportJobId}/download`,

  validate: (projectId: string) =>
    api.get<ExportValidation>(`/api/projects/${projectId}/export/validate`).then((r) => r.data),

  // Legacy compat
  create: (data: {
    project_id: string
    export_format: string
    asset_ids?: string[]
    options?: Record<string, unknown>
  }) =>
    api
      .post<{ export_job_id: string; job_id: string; asset_count: number }>('/api/export', data)
      .then((r) => r.data),

  get: (exportJobId: string) =>
    api.get(`/api/export/${exportJobId}`).then((r) => r.data),
}

// ── Ranking (enhanced) ────────────────────────────────────────────────────────

export const rankingApi = {
  createSession: (
    projectId: string,
    opts: { name?: string; engine?: string; scope?: string; asset_ids?: string[]; strategy?: string }
  ) =>
    api
      .post<RankingSession>(`/api/projects/${projectId}/ranking/sessions`, {
        name: opts.name ?? 'Ranking Session',
        engine: opts.engine ?? 'openskill',
        scope: opts.scope ?? 'all',
        asset_ids: opts.asset_ids ?? [],
        strategy: opts.strategy ?? 'uncertainty',
      })
      .then((r) => r.data),

  listSessions: (projectId: string) =>
    api.get<RankingSession[]>(`/api/projects/${projectId}/ranking/sessions`).then((r) => r.data),

  getSession: (sessionId: string) =>
    api.get<RankingSession & { leaderboard: LeaderboardEntry[] }>(`/api/ranking/sessions/${sessionId}`).then((r) => r.data),

  getNextPair: (sessionId: string, strategy = 'uncertainty') =>
    api
      .get<RankingAssetPair>(`/api/ranking/sessions/${sessionId}/next-pair`, { params: { strategy } })
      .then((r) => r.data),

  recordComparison: (
    sessionId: string,
    winnerId: string,
    loserId: string,
    draw = false,
    opts?: { decided_by?: string; ai_explanation?: string; comparison_time_ms?: number }
  ) =>
    api
      .post(`/api/ranking/sessions/${sessionId}/compare`, {
        winner_id: winnerId,
        loser_id: loserId,
        draw,
        ...(opts ?? {}),
      })
      .then((r) => r.data),

  getLeaderboard: (sessionId: string, limit = 100) =>
    api
      .get<LeaderboardEntry[]>(`/api/ranking/sessions/${sessionId}/leaderboard`, { params: { limit } })
      .then((r) => r.data),

  applyRankings: (sessionId: string) =>
    api.post(`/api/ranking/sessions/${sessionId}/apply`).then((r) => r.data),

  aiJudgeAsset: (assetId: string, provider = 'auto') =>
    api
      .post<AIJudgeResult>(`/api/assets/${assetId}/ai-judge`, null, { params: { provider } })
      .then((r) => r.data),

  aiJudgeBatch: (projectId: string, assetIds?: string[], provider = 'auto') =>
    api
      .post<{ job_id: string; asset_count: number }>(`/api/projects/${projectId}/ai-judge/batch`, assetIds ?? null, {
        params: { provider },
      })
      .then((r) => r.data),

  aiCompare: (sessionId: string, assetIdA: string, assetIdB: string, provider = 'auto') =>
    api
      .post<AIJudgeComparisonResult>(`/api/ranking/sessions/${sessionId}/ai-compare`, {
        asset_id_a: assetIdA,
        asset_id_b: assetIdB,
        provider,
      })
      .then((r) => r.data),
}

export default api
