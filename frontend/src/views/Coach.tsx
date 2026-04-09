import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  Info,
  XCircle,
  TrendingUp,
  Zap,
  Users,
  Image,
  BarChart2,
  Shield,
  Award,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  PieChart,
  Pie,
  ResponsiveContainer,
} from 'recharts'
import { useProjectStore } from '@/stores/useProjectStore'
import { useAssetStore } from '@/stores/useAssetStore'
import { coachApi, assetsApi } from '@/hooks/useApi'
import { useToast } from '@/components/providers/ToastProvider'
import type { CoachIssue, IssueSeverity } from '@/types/api'

// ── Helpers ────────────────────────────────────────────────────────────────────

function severityBgClass(s: IssueSeverity): string {
  switch (s) {
    case 'critical': return 'bg-red-950 border-red-800 text-red-300'
    case 'high':     return 'bg-orange-950 border-orange-800 text-orange-300'
    case 'medium':   return 'bg-yellow-950 border-yellow-800 text-yellow-300'
    case 'low':      return 'bg-blue-950 border-blue-800 text-blue-300'
  }
}

function SeverityBadge({ severity }: { severity: IssueSeverity }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold border uppercase tracking-wider ${severityBgClass(severity)}`}>
      {severity}
    </span>
  )
}

function SeverityIcon({ severity }: { severity: IssueSeverity }) {
  switch (severity) {
    case 'critical': return <XCircle size={15} className="text-red-400 flex-shrink-0" />
    case 'high':     return <AlertTriangle size={15} className="text-orange-400 flex-shrink-0" />
    case 'medium':   return <AlertTriangle size={15} className="text-yellow-400 flex-shrink-0" />
    case 'low':      return <Info size={15} className="text-blue-400 flex-shrink-0" />
  }
}

function gradeTextClass(grade: string): string {
  switch (grade) {
    case 'A': return 'text-green-400'
    case 'B': return 'text-blue-400'
    case 'C': return 'text-yellow-400'
    case 'D': return 'text-orange-400'
    default:  return 'text-red-400'
  }
}

function gradeRingClass(grade: string): string {
  switch (grade) {
    case 'A': return 'ring-green-500'
    case 'B': return 'ring-blue-500'
    case 'C': return 'ring-yellow-500'
    case 'D': return 'ring-orange-500'
    default:  return 'ring-red-500'
  }
}

function qualityBadgeClass(quality: string): string {
  switch (quality) {
    case 'excellent': return 'bg-green-950 text-green-300'
    case 'good':      return 'bg-blue-950 text-blue-300'
    case 'fair':      return 'bg-yellow-950 text-yellow-300'
    default:          return 'bg-red-950 text-red-300'
  }
}

const CHART_COLORS = [
  '#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd',
  '#818cf8', '#60a5fa', '#34d399', '#fbbf24',
]

function distToChartData(dist: Record<string, number>) {
  return Object.entries(dist).map(([name, value]) => ({ name, value }))
}

const RECHARTS_TOOLTIP_STYLE = {
  background: 'var(--surface-elevated, #1e1e2e)',
  border: '1px solid var(--border, #333)',
  borderRadius: 6,
  fontSize: 12,
}

// ── IssueRow ───────────────────────────────────────────────────────────────────

function IssueRow({
  issue,
  onFix,
  isFixing,
}: {
  issue: CoachIssue
  onFix: (issue: CoachIssue) => void
  isFixing: boolean
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border border-[var(--border)] rounded-lg overflow-hidden">
      <div className="flex items-start gap-3 p-3">
        <div className="mt-0.5">
          <SeverityIcon severity={issue.severity} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <SeverityBadge severity={issue.severity} />
            <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--border)] text-[var(--text-secondary)] uppercase tracking-wide">
              {issue.category}
            </span>
            <span className="text-sm font-medium text-[var(--text-primary)]">{issue.title}</span>
          </div>
          <p className="text-xs text-[var(--text-secondary)] mb-1">{issue.description}</p>
          <span className="text-xs text-[var(--text-secondary)]">
            {issue.affected_count} affected
          </span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {issue.auto_fixable && issue.fix_action && (
            <button
              onClick={() => onFix(issue)}
              disabled={isFixing}
              className="btn btn-sm btn-primary flex items-center gap-1"
            >
              {isFixing
                ? <RefreshCw size={12} className="animate-spin" />
                : <Zap size={12} />}
              Auto-fix
            </button>
          )}
          <button
            onClick={() => setExpanded(p => !p)}
            className="btn btn-sm btn-secondary"
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>
      {expanded && (
        <div className="border-t border-[var(--border)] bg-[var(--border)]/10 px-4 py-3">
          <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">Recommendation</p>
          <p className="text-sm text-[var(--text-primary)]">{issue.recommendation}</p>
        </div>
      )}
    </div>
  )
}

// ── ThumbnailStrip ─────────────────────────────────────────────────────────────

function ThumbnailStrip({ assetIds, maxShow = 8 }: { assetIds: string[]; maxShow?: number }) {
  const shown = assetIds.slice(0, maxShow)
  const rest = assetIds.length - shown.length
  if (assetIds.length === 0) {
    return <p className="text-xs text-[var(--text-secondary)] italic">None identified</p>
  }
  return (
    <div className="flex flex-wrap gap-1 mt-2">
      {shown.map(id => (
        <img
          key={id}
          src={assetsApi.thumbnailUrl(id, 128)}
          alt=""
          className="w-10 h-10 rounded object-cover border border-[var(--border)]"
          onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
        />
      ))}
      {rest > 0 && (
        <div className="w-10 h-10 rounded border border-[var(--border)] flex items-center justify-center text-xs text-[var(--text-secondary)]">
          +{rest}
        </div>
      )}
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function Coach() {
  const { activeProject } = useProjectStore()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { success, info, error: toastError } = useToast()
  const setSelection = useAssetStore((state) => state.setSelection)
  const clearFilters = useAssetStore((state) => state.clearFilters)
  const setSortBy = useAssetStore((state) => state.setSortBy)
  const setSortDir = useAssetStore((state) => state.setSortDir)
  const setPage = useAssetStore((state) => state.setPage)
  const [fixingIssueId, setFixingIssueId] = useState<string | null>(null)

  const {
    data: report,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['coach-report', activeProject?.id],
    queryFn: () =>
      coachApi.analyze(activeProject!.id, activeProject?.trigger_word ?? undefined),
    enabled: !!activeProject?.id,
    staleTime: 5 * 60 * 1000,
  })

  const fixMutation = useMutation({
    mutationFn: ({ action, assetIds }: { action: string; assetIds: string[] }) =>
      coachApi.applyAction(activeProject!.id, action, assetIds),
    onSuccess: data => {
      success(`Fixed ${data.affected} assets (${data.action})`)
      queryClient.invalidateQueries({ queryKey: ['coach-report', activeProject?.id] })
      queryClient.invalidateQueries({ queryKey: ['assets'] })
      queryClient.invalidateQueries({ queryKey: ['project-stats'] })
      queryClient.invalidateQueries({ queryKey: ['export-validation'] })
      queryClient.invalidateQueries({ queryKey: ['duplicates'] })
      setFixingIssueId(null)
    },
    onError: () => {
      toastError('Auto-fix failed')
      setFixingIssueId(null)
    },
  })

  const bulkRejectMutation = useMutation({
    mutationFn: (assetIds: string[]) =>
      assetsApi.bulkAction(activeProject!.id, 'reject', assetIds),
    onSuccess: data => {
      success(`Rejected ${data.affected} assets`)
      queryClient.invalidateQueries({ queryKey: ['coach-report', activeProject?.id] })
      queryClient.invalidateQueries({ queryKey: ['assets'] })
      queryClient.invalidateQueries({ queryKey: ['project-stats'] })
      queryClient.invalidateQueries({ queryKey: ['export-validation'] })
      queryClient.invalidateQueries({ queryKey: ['duplicates'] })
    },
    onError: () => toastError('Bulk reject failed'),
  })

  function handleFix(issue: CoachIssue) {
    if (!issue.fix_action || !activeProject) return
    setFixingIssueId(issue.id)
    fixMutation.mutate({ action: issue.fix_action, assetIds: issue.affected_asset_ids })
  }

  function focusAssetSet(
    ids: string[],
    {
      destination,
      label,
      sortDir,
    }: {
      destination: '/gallery' | '/export'
      label: string
      sortDir: 'asc' | 'desc'
    }
  ) {
    if (ids.length === 0) {
      info(`No ${label.toLowerCase()} available yet.`)
      return
    }

    clearFilters()
    setSortBy('composite_score')
    setSortDir(sortDir)
    setPage(1)
    setSelection(ids)
    success(`Selected ${ids.length} ${label.toLowerCase()}.`)
    navigate(destination)
  }

  if (!activeProject) {
    return (
      <div className="p-6 flex items-center justify-center h-full">
        <p className="text-[var(--text-secondary)]">Select a project to run Dataset Coach.</p>
      </div>
    )
  }

  const severityOrder: Record<IssueSeverity, number> = { critical: 0, high: 1, medium: 2, low: 3 }
  const sortedIssues = report
    ? [...report.issues].sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity])
    : []

  const shotTypeData   = distToChartData(report?.shot_type_distribution ?? {})
  const headAngleData  = distToChartData(report?.head_angle_distribution ?? {})
  const expressionData = distToChartData(report?.expression_distribution ?? {})
  const scoreDistData  = distToChartData(report?.score_distribution ?? {})

  const qualityPct = report ? Math.round((report.avg_composite_score ?? 0) * 100) : 0
  const captionPct =
    report && report.total_assets > 0
      ? Math.round((report.captioned_count / report.total_assets) * 100)
      : 0

  return (
    <div className="p-6 overflow-y-auto h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">Dataset Coach</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            AI-powered dataset quality analysis and recommendations
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="btn btn-primary flex items-center gap-2"
        >
          <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          {isFetching ? 'Analyzing...' : 'Run Analysis'}
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-24">
          <RefreshCw size={24} className="animate-spin text-[var(--text-secondary)]" />
          <span className="ml-3 text-[var(--text-secondary)]">Running analysis...</span>
        </div>
      )}

      {!isLoading && !report && (
        <div className="flex flex-col items-center justify-center py-24 gap-3">
          <BarChart2 size={40} className="text-[var(--text-secondary)]" />
          <p className="text-[var(--text-secondary)]">
            Click "Run Analysis" to evaluate your dataset.
          </p>
        </div>
      )}

      {report && (
        <>
          {/* Overview Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
            {/* Training Readiness */}
            <div className="card p-4 flex flex-col gap-2">
              <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)] font-medium uppercase tracking-wide">
                <Award size={14} />
                Training Readiness
              </div>
              <div className="flex items-end gap-3">
                <span
                  className={`text-4xl font-black ring-2 rounded-lg w-14 h-14 flex items-center justify-center ${gradeTextClass(report.training_readiness_grade)} ${gradeRingClass(report.training_readiness_grade)}`}
                >
                  {report.training_readiness_grade}
                </span>
                <div>
                  <p className="text-2xl font-bold text-[var(--text-primary)]">
                    {Math.round(report.training_readiness_score)}
                    <span className="text-sm font-normal text-[var(--text-secondary)]">/100</span>
                  </p>
                  <p className="text-xs text-[var(--text-secondary)]">{report.estimated_training_quality}</p>
                </div>
              </div>
            </div>

            {/* Quality */}
            <div className="card p-4 flex flex-col gap-2">
              <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)] font-medium uppercase tracking-wide">
                <Shield size={14} />
                Quality
              </div>
              <p className="text-3xl font-bold text-[var(--text-primary)]">
                {qualityPct}
                <span className="text-base font-normal text-[var(--text-secondary)]">%</span>
              </p>
              <p className="text-xs text-[var(--text-secondary)]">
                avg composite · {report.low_quality_count} low quality
              </p>
              {report.blur_count > 0 && (
                <p className="text-xs text-orange-400">{report.blur_count} blurry</p>
              )}
            </div>

            {/* Diversity */}
            <div className="card p-4 flex flex-col gap-2">
              <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)] font-medium uppercase tracking-wide">
                <Users size={14} />
                Diversity
              </div>
              <p className="text-3xl font-bold text-[var(--text-primary)]">
                {sortedIssues.filter(i => i.category === 'diversity').length}
                <span className="text-base font-normal text-[var(--text-secondary)]"> issues</span>
              </p>
              <p className="text-xs text-[var(--text-secondary)]">
                {report.near_duplicate_clusters} near-dup clusters · redundancy {Math.round(report.redundancy_score * 100)}%
              </p>
            </div>

            {/* Captions */}
            <div className="card p-4 flex flex-col gap-2">
              <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)] font-medium uppercase tracking-wide">
                <Image size={14} />
                Captions
              </div>
              <p className="text-3xl font-bold text-[var(--text-primary)]">
                {captionPct}
                <span className="text-base font-normal text-[var(--text-secondary)]">%</span>
              </p>
              <p className="text-xs text-[var(--text-secondary)]">
                {report.captioned_count}/{report.total_assets} captioned
              </p>
              {report.uncaptioned_count > 0 && (
                <p className="text-xs text-orange-400">{report.uncaptioned_count} uncaptioned</p>
              )}
            </div>
          </div>

          {/* Coverage Section */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
            {shotTypeData.length > 0 && (
              <div className="card p-4">
                <h3 className="text-sm font-medium text-[var(--text-primary)] mb-3 flex items-center gap-2">
                  <BarChart2 size={14} /> Shot Type Distribution
                </h3>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={shotTypeData} layout="vertical" margin={{ left: 0, right: 8 }}>
                    <XAxis type="number" hide />
                    <YAxis type="category" dataKey="name" width={90} tick={{ fontSize: 11, fill: 'var(--text-secondary)' }} />
                    <RechartsTooltip contentStyle={RECHARTS_TOOLTIP_STYLE} />
                    <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                      {shotTypeData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {headAngleData.length > 0 && (
              <div className="card p-4">
                <h3 className="text-sm font-medium text-[var(--text-primary)] mb-3 flex items-center gap-2">
                  <Users size={14} /> Head Angle Distribution
                </h3>
                <ResponsiveContainer width="100%" height={180}>
                  <PieChart>
                    <Pie
                      data={headAngleData}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      dataKey="value"
                      nameKey="name"
                      label={({ name, percent }) => `${name} ${Math.round((percent ?? 0) * 100)}%`}
                      labelLine={false}
                    >
                      {headAngleData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                    </Pie>
                    <RechartsTooltip contentStyle={RECHARTS_TOOLTIP_STYLE} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}

            {expressionData.length > 0 && (
              <div className="card p-4">
                <h3 className="text-sm font-medium text-[var(--text-primary)] mb-3 flex items-center gap-2">
                  <TrendingUp size={14} /> Expression Distribution
                </h3>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={expressionData}>
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                    <YAxis hide />
                    <RechartsTooltip contentStyle={RECHARTS_TOOLTIP_STYLE} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                      {expressionData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {scoreDistData.length > 0 && (
              <div className="card p-4">
                <h3 className="text-sm font-medium text-[var(--text-primary)] mb-3 flex items-center gap-2">
                  <Shield size={14} /> Score Distribution
                </h3>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={scoreDistData}>
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                    <YAxis hide />
                    <RechartsTooltip contentStyle={RECHARTS_TOOLTIP_STYLE} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                      {scoreDistData.map((entry, i) => {
                        const bucket = parseFloat(entry.name)
                        const fill = bucket >= 0.7 ? '#34d399' : bucket >= 0.4 ? '#fbbf24' : '#f87171'
                        return <Cell key={i} fill={fill} />
                      })}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Issues List */}
          {sortedIssues.length > 0 && (
            <div className="card p-4 mb-6">
              <h2 className="text-base font-semibold text-[var(--text-primary)] mb-4 flex items-center gap-2">
                <AlertTriangle size={16} />
                Issues ({sortedIssues.length})
              </h2>
              <div className="flex flex-col gap-2">
                {sortedIssues.map(issue => (
                  <IssueRow
                    key={issue.id}
                    issue={issue}
                    onFix={handleFix}
                    isFixing={fixingIssueId === issue.id && fixMutation.isPending}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Recommendations Panel */}
          <div className="grid lg:grid-cols-3 gap-4 mt-6">
            <div className="card p-4">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1 flex items-center gap-2">
                <XCircle size={14} className="text-red-400" />
                Worst Offenders
              </h3>
              <p className="text-xs text-[var(--text-secondary)] mb-2">
                Remove these first to improve dataset quality.
              </p>
              <ThumbnailStrip assetIds={report.remove_first} />
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => focusAssetSet(report.remove_first, { destination: '/gallery', label: 'Remove Candidates', sortDir: 'asc' })}
                  className="btn btn-secondary btn-sm flex-1"
                >
                  Review in Gallery
                </button>
                {report.remove_first.length > 0 && (
                  <button
                    onClick={() => bulkRejectMutation.mutate(report.remove_first)}
                    disabled={bulkRejectMutation.isPending}
                    className="btn btn-danger btn-sm flex-1 flex items-center justify-center gap-1"
                  >
                    {bulkRejectMutation.isPending
                      ? <RefreshCw size={12} className="animate-spin" />
                      : null}
                    Bulk Reject
                  </button>
                )}
              </div>
            </div>

            <div className="card p-4">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1 flex items-center gap-2">
                <CheckCircle size={14} className="text-green-400" />
                Best Assets
              </h3>
              <p className="text-xs text-[var(--text-secondary)] mb-2">
                Prioritize these for training. The preview shows the top of the recommended subset.
              </p>
              <ThumbnailStrip assetIds={report.keep_first} />
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => focusAssetSet(report.recommended_selection, { destination: '/gallery', label: 'Recommended Training Set', sortDir: 'desc' })}
                  className="btn btn-primary btn-sm flex-1"
                >
                  Review Recommended
                </button>
                <button
                  onClick={() => focusAssetSet(report.recommended_selection, { destination: '/export', label: 'Recommended Training Set', sortDir: 'desc' })}
                  className="btn btn-secondary btn-sm flex-1"
                >
                  Export Recommended
                </button>
              </div>
            </div>

            <div className="card p-4">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1 flex items-center gap-2">
                <Info size={14} className="text-blue-400" />
                Coverage Gaps
              </h3>
              <p className="text-xs text-[var(--text-secondary)] mb-2">
                Capture these to improve diversity.
              </p>
              {report.missing_coverage.length === 0 ? (
                <p className="text-xs text-[var(--text-secondary)] italic">No gaps detected</p>
              ) : (
                <ul className="space-y-1 mt-1">
                  {report.missing_coverage.map((item, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-xs text-[var(--text-secondary)]">
                      <span className="text-blue-400 mt-0.5">•</span>
                      {item}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* Action Plan + Training Summary */}
          <div className="grid lg:grid-cols-2 gap-4 mt-4">
            <div className="card p-4">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
                <Zap size={14} className="text-yellow-400" />
                Action Plan
              </h3>
              {report.improvement_actions.length === 0 ? (
                <p className="text-xs text-[var(--text-secondary)] italic">No specific actions needed.</p>
              ) : (
                <ol className="space-y-2">
                  {report.improvement_actions.map((action, i) => (
                    <li key={i} className="flex gap-2 text-sm text-[var(--text-secondary)]">
                      <span className="flex-shrink-0 w-5 h-5 rounded-full bg-[var(--accent)] text-white text-xs flex items-center justify-center font-bold">
                        {i + 1}
                      </span>
                      {action}
                    </li>
                  ))}
                </ol>
              )}
            </div>

            <div className="card p-4">
              <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3 flex items-center gap-2">
                <Award size={14} />
                Training Readiness Summary
              </h3>
              <p className="text-xs text-[var(--text-secondary)] mb-3">
                Recommended curated set size: about {report.selection_target_count} images.
              </p>
              <div className="flex items-center gap-4 mb-3">
                <span className={`text-4xl font-black ${gradeTextClass(report.training_readiness_grade)}`}>
                  {report.training_readiness_grade}
                </span>
                <div>
                  <p className="text-lg font-bold text-[var(--text-primary)]">
                    {Math.round(report.training_readiness_score)}/100
                  </p>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${qualityBadgeClass(report.estimated_training_quality)}`}>
                    {report.estimated_training_quality}
                  </span>
                </div>
              </div>
              <p className="text-sm text-[var(--text-secondary)]">{report.training_readiness_summary}</p>
            </div>
          </div>

          <div className="card p-4 mt-4">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1 flex items-center gap-2">
              <TrendingUp size={14} className="text-blue-400" />
              Next-Best Additions
            </h3>
            <p className="text-xs text-[var(--text-secondary)] mb-2">
              Use these after the recommended subset if you need a larger training set or want better coverage.
            </p>
            <ThumbnailStrip assetIds={report.next_best} />
            {report.next_best.length === 0 && (
              <p className="text-xs text-[var(--text-secondary)] italic mt-2">
                No additional candidates recommended yet.
              </p>
            )}
            {report.next_best.length > 0 && (
              <button
                onClick={() => focusAssetSet(report.next_best, { destination: '/gallery', label: 'Next-Best Additions', sortDir: 'desc' })}
                className="btn btn-secondary btn-sm mt-3 w-full"
              >
                Review Next-Best
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
