// TypeScript types matching the backend Pydantic schemas

export interface Project {
  id: string
  name: string
  description: string | null
  trigger_word: string | null
  subject_type: string | null
  asset_count: number
  reviewed_count: number
  flagged_count: number
  rejected_count: number
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  name: string
  description?: string
  trigger_word?: string
  subject_type?: string
}

export interface RuntimeTaskCatalogEntry {
  task_key: string
  label: string
  provider_type: string
  description: string
  selected_provider: string | null
  effective_provider: string | null
  available_providers: string[]
}

export interface ProjectRuntimeConfig {
  project_id: string
  runtime_mode: 'local' | 'hybrid' | 'hosted'
  task_provider_overrides: Record<string, string>
  task_provider_options: Record<string, Record<string, unknown>>
  benchmark_preferences: Record<string, unknown>
  task_catalog: RuntimeTaskCatalogEntry[]
}

// ── Assets ────────────────────────────────────────────────────────────────────

export type ReviewState = 'pending' | 'reviewed' | 'approved' | 'rejected' | 'flagged'
export type ShotType = 'extreme_closeup' | 'closeup' | 'medium' | 'wide' | 'full_body' | 'unknown'

export interface BoundingBox {
  x1: number
  y1: number
  x2: number
  y2: number
  confidence: number
}

export interface AssetSummary {
  id: string
  filename: string
  width: number | null
  height: number | null
  composite_score: number | null
  face_count: number
  review_state: ReviewState
  is_flagged: boolean
  is_rejected: boolean
  is_augmented: boolean
  shot_type: ShotType
  thumbnail_path: string | null
  active_caption_id: string | null
  duplicate_cluster_id: string | null
  trueskill_mu: number
  imported_at: string
}

export interface AssetDetail extends AssetSummary {
  filepath: string
  file_size: number | null
  mime_type: string | null
  sha256_hash: string | null
  phash: string | null
  analyzed_at: string | null
  technical_quality: number | null
  aesthetic_score: number | null
  face_quality: number | null
  training_usefulness: number | null
  score_breakdown: Record<string, number> | null
  primary_face_bbox: BoundingBox | null
  head_pose_yaw: number | null
  head_pose_pitch: number | null
  head_pose_roll: number | null
  age_estimate: number | null
  gender_estimate: string | null
  dominant_emotion: string | null
  gaze_direction: string | null
  is_indoor: boolean | null
  scene_class: string | null
  scene_tags: string[] | null
  object_tags: string[] | null
  caption_provider: string | null
  augmentation_source_id: string | null
  trueskill_sigma: number
  elo_rating: number
  ranking_comparisons_count: number
}

export interface AssetListResponse {
  items: AssetSummary[]
  total: number
  page: number
  page_size: number
  has_next: boolean
}

export interface AssetUpdate {
  review_state?: ReviewState
  is_flagged?: boolean
  is_rejected?: boolean
  rejection_reason?: string
  shot_type?: ShotType
}

export type DuplicateClusterType = 'exact' | 'phash' | 'embedding' | 'face'

export interface DuplicateImage {
  id: string
  filepath: string
  thumbnail_url: string
  score: number
  quality_score?: number | null
  keep: boolean
}

export interface DuplicateCluster {
  id: string
  cluster_type: DuplicateClusterType
  image_count: number
  images: DuplicateImage[]
  best_id: string
}

export interface DuplicatesResponse {
  clusters: DuplicateCluster[]
  total_clusters: number
  total_duplicates: number
}

// ── Captions ──────────────────────────────────────────────────────────────────

export type CaptionStyle = 'natural' | 'concise' | 'danbooru_tags' | 'wd_tags' | 'training_literal'

export interface CaptionVersion {
  id: string
  asset_id: string
  text: string
  style: CaptionStyle
  provider: string
  model: string | null
  confidence: number | null
  latency_ms: number | null
  is_edited: boolean
  is_active: boolean
  created_at: string
}

// ── Jobs ──────────────────────────────────────────────────────────────────────

export type JobStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'

export interface Job {
  id: string
  type: string
  status: JobStatus
  progress: number
  message: string
  result: unknown | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

// ── Providers ─────────────────────────────────────────────────────────────────

export interface ProviderHealth {
  ok: boolean
  latency_ms: number
  details: Record<string, unknown>
}

export interface ProviderHealthMap {
  providers: Record<string, Record<string, ProviderHealth>>
  all_ok: boolean
}

// ── Ranking ───────────────────────────────────────────────────────────────────

export interface RankingSession {
  id: string
  project_id: string
  name: string
  ranking_algorithm: string
  asset_scope: string
  selection_strategy: string
  asset_ids_count: number
  skipped_pairs_count: number
  is_active: boolean
  total_comparisons: number
  created_at: string
}

export interface RankingPair {
  a: string
  b: string
}

export interface RatingUpdate {
  id: string
  mu: number
  sigma: number
}

export interface RankingAssetPair {
  asset_a: RankedAsset
  asset_b: RankedAsset
  session_id: string
}

export interface RankedAsset {
  id: string
  filename: string
  trueskill_mu: number
  trueskill_sigma: number
  composite_score: number | null
  face_count: number
  ranking_comparisons_count: number
  thumbnail_url: string
}

export interface LeaderboardEntry {
  asset_id: string
  filename: string
  rank: number
  mu: number
  sigma: number | null
  elo: number | null
  ordinal: number
  comparisons: number
  thumbnail_url: string | null
  ai_composite?: number | null
}

export interface AIJudgeScore {
  score: number
  reason: string
  not_applicable?: boolean
}

export interface AIJudgeResult {
  asset_id: string
  composite: number
  recommendation: 'keep' | 'maybe' | 'remove'
  confidence: 'high' | 'medium' | 'low'
  needs_human_review: boolean
  review_reason: string
  provider_used: string
  is_fallback: boolean
  scores: {
    technical_quality: AIJudgeScore
    aesthetic_quality: AIJudgeScore
    face_clarity: AIJudgeScore
    pose_usefulness: AIJudgeScore
    expression_quality: AIJudgeScore
    background_usefulness: AIJudgeScore
    uniqueness: AIJudgeScore
    training_value: AIJudgeScore
  }
  strengths: string[]
  weaknesses: string[]
}

export interface AIJudgeComparisonResult {
  winner: 'A' | 'B' | 'draw'
  winner_asset_id: string
  confidence: 'high' | 'medium' | 'low'
  margin: 'clear' | 'slight' | 'negligible'
  overall_reasoning: string
  dimensions: {
    technical_quality?: { winner: string; reason: string }
    aesthetic_quality?: { winner: string; reason: string }
    face_clarity?: { winner: string; reason: string }
  }
  a_strengths: string[]
  b_strengths: string[]
  dataset_contribution: { A?: string; B?: string }
  provider_used: string
}

// ── Caption consistency ────────────────────────────────────────────────────────

export interface WordFrequency {
  word: string
  count: number
}

export interface CaptionConsistencyReport {
  total_captioned: number
  total_uncaptioned: number
  avg_length: number
  length_std: number
  common_words: WordFrequency[]
  rare_words: WordFrequency[]
  trigger_word_presence: Record<string, number>
  inconsistent_formatting: string[]
  recommendations: string[]
}

// ── Filters ───────────────────────────────────────────────────────────────────

export interface AssetFilters {
  min_score?: number
  max_score?: number
  review_state?: ReviewState | ''
  shot_type?: ShotType | ''
  has_face?: boolean
  is_flagged?: boolean
  is_rejected?: boolean
  has_caption?: boolean
  has_duplicate?: boolean
  search?: string
}

export type SortField =
  | 'imported_at'
  | 'composite_score'
  | 'aesthetic_score'
  | 'face_quality'
  | 'technical_quality'
  | 'filename'
  | 'trueskill_mu'
  | 'analyzed_at'

export type SortDir = 'asc' | 'desc'

// ── Coach ─────────────────────────────────────────────────────────────────────

export interface CoachRecommendation {
  priority: number
  category: string
  title: string
  description: string
  action: string
  affected_count: number
}

export interface CoachAnalysis {
  project_id: string
  total_assets: number
  reviewed_count: number
  flagged_count: number
  rejected_count: number
  shot_type_dist: Record<string, number>
  emotion_dist: Record<string, number>
  score_dist: Record<string, number>
  pose_yaw_coverage: Record<string, number>
  avg_composite_score: number
  avg_face_quality: number
  avg_aesthetic: number
  pct_with_face: number
  pct_with_caption: number
  pct_duplicates: number
  recommendations: CoachRecommendation[]
}

export type IssueSeverity = 'critical' | 'high' | 'medium' | 'low'
export type IssueCategory = 'quality' | 'diversity' | 'captions' | 'identity' | 'coverage' | 'balance'

export interface CoachIssue {
  id: string
  category: IssueCategory
  severity: IssueSeverity
  title: string
  description: string
  affected_count: number
  affected_asset_ids: string[]
  recommendation: string
  auto_fixable: boolean
  fix_action: string | null
}

export interface CoachReport {
  project_id: string
  analyzed_at: string
  total_assets: number
  approved_assets: number
  shot_type_distribution: Record<string, number>
  head_angle_distribution: Record<string, number>
  expression_distribution: Record<string, number>
  background_distribution: Record<string, number>
  avg_composite_score: number
  score_distribution: Record<string, number>
  low_quality_count: number
  blur_count: number
  exact_duplicate_count: number
  near_duplicate_clusters: number
  redundancy_score: number
  captioned_count: number
  uncaptioned_count: number
  avg_caption_length: number
  trigger_word_coverage: number
  unique_identities: number
  multi_subject_count: number
  face_visibility_score: number
  issues: CoachIssue[]
  remove_first: string[]
  recommended_selection: string[]
  keep_first: string[]
  next_best: string[]
  missing_coverage: string[]
  improvement_actions: string[]
  selection_target_count: number
  training_readiness_score: number
  training_readiness_grade: string
  training_readiness_summary: string
  estimated_training_quality: string
}

// ── Augmentation ──────────────────────────────────────────────────────────────

export interface AugmentationPlan {
  id: string
  operation: string
  reason: string
  gap_addressed: string
  source_asset_id: string | null
  estimated_benefit: number
  params: Record<string, unknown>
  priority: number
}

export interface AugmentationResult {
  id: string
  source_asset_id: string
  output_path: string
  operation: string
  provider: string
  status: 'pending_review' | 'approved' | 'rejected'
  before_score: number | null
  after_score: number | null
  identity_preserved: boolean | null
  created_at: string
  params_used: Record<string, unknown>
  error: string | null
}

// ── Export ────────────────────────────────────────────────────────────────────

export interface ExportJob {
  id: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  job_id?: string | null
  progress: number
  exported_assets: number
  total_assets: number
  output_path: string | null
  error: string | null
  created_at: string
  finished_at: string | null
}

export interface ExportValidation {
  warnings: string[]
  asset_count: number
  captioned_count: number
  approved_count: number
  low_quality_count?: number
}
