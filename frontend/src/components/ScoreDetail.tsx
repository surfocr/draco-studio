import { X, AlertCircle, CheckCircle, Info } from 'lucide-react'

export interface ScoreDimension {
  label: string
  key: string
  score: number        // 0–1
  weight: number       // relative weight
  rationale?: string
  flag?: 'good' | 'warn' | 'bad'
}

export interface ExplainedScore {
  composite: number
  dimensions: ScoreDimension[]
  summary?: string
  recommendations?: string[]
  judge_provider?: string
  latency_ms?: number
}

interface ScoreBarProps {
  score: number
  label: string
  rationale?: string
  flag?: 'good' | 'warn' | 'bad'
}

function ScoreBar({ score, label, rationale, flag }: ScoreBarProps) {
  const pct = Math.round(score * 100)
  const barColor = score > 0.7 ? 'bg-emerald-500' : score > 0.4 ? 'bg-amber-500' : 'bg-red-500'
  const textColor = score > 0.7 ? 'text-emerald-400' : score > 0.4 ? 'text-amber-400' : 'text-red-400'
  const FlagIcon = flag === 'good' ? CheckCircle : flag === 'bad' ? AlertCircle : null

  return (
    <div className="mb-3">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          {FlagIcon && (
            <FlagIcon size={12} className={flag === 'good' ? 'text-emerald-400' : 'text-red-400'} />
          )}
          <span className="text-zinc-300 text-xs font-medium">{label}</span>
        </div>
        <span className={`text-xs font-mono font-semibold ${textColor}`}>{pct}%</span>
      </div>
      <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {rationale && (
        <p className="text-zinc-500 text-xs mt-1 leading-relaxed">{rationale}</p>
      )}
    </div>
  )
}

interface Props {
  score: ExplainedScore
  imageSrc?: string
  filename?: string
  onClose?: () => void
}

export function ScoreDetailDrawer({ score, imageSrc, filename, onClose }: Props) {
  const composite_pct = Math.round(score.composite * 100)
  const compositeColor = score.composite > 0.7 ? 'text-emerald-400'
    : score.composite > 0.4 ? 'text-amber-400' : 'text-red-400'

  return (
    <div className="flex flex-col h-full bg-zinc-900 border-l border-zinc-800 w-80">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-zinc-800">
        <div>
          <h3 className="text-white text-sm font-semibold">AI Score Breakdown</h3>
          {filename && <p className="text-zinc-500 text-xs truncate max-w-52">{filename}</p>}
        </div>
        {onClose && (
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
            <X size={16} />
          </button>
        )}
      </div>

      {/* Image preview */}
      {imageSrc && (
        <div className="mx-4 mt-3 rounded-lg overflow-hidden bg-zinc-800 aspect-video">
          <img src={imageSrc} alt={filename} className="w-full h-full object-contain" />
        </div>
      )}

      {/* Composite score */}
      <div className="mx-4 mt-3 p-3 rounded-lg bg-zinc-800/50 border border-zinc-700/50 flex items-center gap-3">
        <div className={`text-3xl font-bold font-mono ${compositeColor}`}>
          {composite_pct}
        </div>
        <div>
          <div className="text-white text-xs font-medium">Composite Score</div>
          {score.judge_provider && (
            <div className="text-zinc-500 text-xs">via {score.judge_provider}</div>
          )}
        </div>
      </div>

      {/* Summary */}
      {score.summary && (
        <div className="mx-4 mt-3 p-3 rounded-lg bg-zinc-800/30 border border-zinc-700/30">
          <div className="flex items-start gap-2">
            <Info size={12} className="text-violet-400 mt-0.5 flex-shrink-0" />
            <p className="text-zinc-300 text-xs leading-relaxed">{score.summary}</p>
          </div>
        </div>
      )}

      {/* Dimension scores */}
      <div className="flex-1 overflow-y-auto p-4">
        <h4 className="text-zinc-400 text-xs font-semibold uppercase tracking-wider mb-3">Score Breakdown</h4>
        {score.dimensions.map(dim => (
          <ScoreBar
            key={dim.key}
            score={dim.score}
            label={dim.label}
            rationale={dim.rationale}
            flag={dim.flag}
          />
        ))}

        {/* Recommendations */}
        {score.recommendations && score.recommendations.length > 0 && (
          <div className="mt-4">
            <h4 className="text-zinc-400 text-xs font-semibold uppercase tracking-wider mb-2">Recommendations</h4>
            <ul className="space-y-1.5">
              {score.recommendations.map((rec, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-zinc-400">
                  <span className="text-violet-400 flex-shrink-0 mt-0.5">→</span>
                  {rec}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

/** Compact inline score badges for gallery cards */
export function CompactScoreBadges({ dimensions }: { dimensions: ScoreDimension[] }) {
  const worst = [...dimensions].sort((a, b) => a.score - b.score).slice(0, 2)
  return (
    <div className="flex gap-1 flex-wrap">
      {worst.map(d => (
        <span
          key={d.key}
          title={`${d.label}: ${Math.round(d.score * 100)}%`}
          className={`text-[9px] px-1 py-0.5 rounded border ${
            d.score < 0.4
              ? 'bg-red-500/10 text-red-400 border-red-500/20'
              : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
          }`}
        >
          {d.label.replace(' ', '').slice(0, 4).toLowerCase()}
        </span>
      ))}
    </div>
  )
}
