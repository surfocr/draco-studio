import React, { useState, useRef, useEffect } from 'react'
import { HelpCircle } from 'lucide-react'

interface TooltipProps {
  content: string | React.ReactNode
  title?: string
  hint?: string
  side?: 'top' | 'bottom' | 'left' | 'right'
  children: React.ReactNode
  delayMs?: number
  showHintButton?: boolean
}

export function Tooltip({
  content,
  title,
  hint,
  side = 'top',
  children,
  delayMs = 300,
  showHintButton = false,
}: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const [hintExpanded, setHintExpanded] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function handleMouseEnter() {
    timerRef.current = setTimeout(() => setVisible(true), delayMs)
  }

  function handleMouseLeave() {
    if (timerRef.current) clearTimeout(timerRef.current)
    setVisible(false)
    setHintExpanded(false)
  }

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  // Position class based on side
  function positionClasses() {
    switch (side) {
      case 'top':
        return 'bottom-full left-1/2 -translate-x-1/2 mb-2'
      case 'bottom':
        return 'top-full left-1/2 -translate-x-1/2 mt-2'
      case 'left':
        return 'right-full top-1/2 -translate-y-1/2 mr-2'
      case 'right':
        return 'left-full top-1/2 -translate-y-1/2 ml-2'
    }
  }

  return (
    <div
      className="relative inline-flex"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}

      {visible && (
        <div
          className={`absolute ${positionClasses()} z-50 w-56 max-w-xs rounded-lg shadow-xl bg-[var(--surface-elevated,#1e1e2e)] border border-[var(--border)] p-2.5 pointer-events-auto`}
        >
          {title && (
            <div className="font-medium text-xs text-[var(--text-primary)] mb-1">{title}</div>
          )}
          <div className="text-xs text-[var(--text-secondary)] leading-relaxed">{content}</div>
          {showHintButton && hint && (
            <div className="mt-1.5">
              <button
                onClick={e => {
                  e.stopPropagation()
                  setHintExpanded(p => !p)
                }}
                className="text-xs text-[var(--accent)] hover:underline"
              >
                {hintExpanded ? 'Hide hint' : '? Show hint'}
              </button>
              {hintExpanded && (
                <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">{hint}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function TooltipIcon({ content, title }: { content: string; title?: string }) {
  return (
    <Tooltip content={content} title={title} side="top">
      <HelpCircle
        size={14}
        className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-help transition-colors"
      />
    </Tooltip>
  )
}
