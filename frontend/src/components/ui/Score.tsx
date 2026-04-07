/* Score component */
import { clsx } from 'clsx'

interface ScoreProps {
  value: number | null | undefined
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
  className?: string
}

function scoreColor(value: number): string {
  if (value >= 0.8) return '#22c55e'
  if (value >= 0.6) return '#84cc16'
  if (value >= 0.4) return '#f59e0b'
  return '#ef4444'
}

export function Score({ value, size = 'md', showLabel = false, className }: ScoreProps) {
  if (value == null) {
    return (
      <span className={clsx('text-text-secondary font-mono', className)}>
        {size !== 'sm' && '—'}
      </span>
    )
  }

  const pct = Math.round(value * 100)
  const color = scoreColor(value)

  const sizeClasses = {
    sm: 'text-[10px] px-1 py-0.5',
    md: 'text-xs px-1.5 py-0.5',
    lg: 'text-sm px-2 py-1',
  }

  return (
    <span
      className={clsx(
        'font-mono font-semibold rounded',
        sizeClasses[size],
        className
      )}
      style={{
        color,
        background: `${color}18`,
      }}
    >
      {pct}
      {showLabel && '%'}
    </span>
  )
}
