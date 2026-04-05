import React, { useState, useEffect, useCallback } from 'react'
import { X, ArrowRight, ArrowLeft } from 'lucide-react'

// ── Types ──────────────────────────────────────────────────────────────────────

interface TourStep {
  id: string
  target: string
  title: string
  content: string
  side: 'top' | 'bottom' | 'left' | 'right'
  action?: 'click' | 'hover' | null
}

// ── Tour Steps ─────────────────────────────────────────────────────────────────

const FIRST_RUN_TOUR: TourStep[] = [
  {
    id: 'welcome',
    target: '.app-shell',
    title: 'Welcome to Draco Dataset Studio',
    content:
      "A professional tool for curating, analyzing, and exporting ML training datasets. Let's take a quick tour.",
    side: 'bottom',
  },
  {
    id: 'import',
    target: '#dropzone',
    title: 'Import Your Images',
    content:
      'Drag and drop images or folders here to start building your dataset. Supports JPG, PNG, WebP.',
    side: 'bottom',
  },
  {
    id: 'gallery',
    target: '#nav-gallery',
    title: 'Gallery View',
    content:
      'Browse all imported images with quality scores, face analysis data, and filtering options.',
    side: 'right',
  },
  {
    id: 'captions',
    target: '#nav-captions',
    title: 'Caption Workflow',
    content:
      'Generate AI captions using Ollama, Gemini, Florence-2 or other providers. Edit and activate captions per image.',
    side: 'right',
  },
  {
    id: 'ranking',
    target: '#nav-ranking',
    title: 'Ranking Arena',
    content:
      'Compare images head-to-head using TrueSkill ranking. Surface the best images for training.',
    side: 'right',
  },
  {
    id: 'coach',
    target: '#nav-coach',
    title: 'Dataset Coach',
    content:
      'Get AI-powered recommendations for improving your dataset quality, diversity, and training readiness.',
    side: 'right',
  },
  {
    id: 'export',
    target: '#nav-export',
    title: 'Export for Training',
    content:
      'Export in LoRA, Kohya SS, or ZIP format with one click. Captions included automatically.',
    side: 'right',
  },
]

const TOUR_DONE_KEY = 'draco_tour_done'

// ── Tooltip position helpers ───────────────────────────────────────────────────

interface TooltipStyle {
  top?: number | string
  left?: number | string
  right?: number | string
  bottom?: number | string
  transform?: string
}

function computeTooltipStyle(
  rect: DOMRect,
  side: TourStep['side'],
  tooltipWidth = 288,
  tooltipHeight = 200,
): TooltipStyle {
  const margin = 16
  switch (side) {
    case 'bottom':
      return {
        top: rect.bottom + margin,
        left: Math.max(margin, rect.left + rect.width / 2 - tooltipWidth / 2),
      }
    case 'top':
      return {
        top: rect.top - tooltipHeight - margin,
        left: Math.max(margin, rect.left + rect.width / 2 - tooltipWidth / 2),
      }
    case 'right':
      return {
        top: Math.max(margin, rect.top + rect.height / 2 - tooltipHeight / 2),
        left: rect.right + margin,
      }
    case 'left':
      return {
        top: Math.max(margin, rect.top + rect.height / 2 - tooltipHeight / 2),
        left: rect.left - tooltipWidth - margin,
      }
  }
}

// ── TourSystem Component ───────────────────────────────────────────────────────

interface TourSystemProps {
  onComplete?: () => void
}

export function TourSystem({ onComplete }: TourSystemProps) {
  const [step, setStep] = useState(0)
  const [visible, setVisible] = useState(false)
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null)

  const currentStep = FIRST_RUN_TOUR[step]

  // On mount, check if tour has already been completed
  useEffect(() => {
    const done = localStorage.getItem(TOUR_DONE_KEY)
    if (!done) {
      setVisible(true)
    }
  }, [])

  // Update target rect when step changes
  useEffect(() => {
    if (!visible || !currentStep) return

    function measure() {
      const el = document.querySelector(currentStep.target)
      if (el) {
        setTargetRect(el.getBoundingClientRect())
      } else {
        setTargetRect(null)
      }
    }

    measure()
    // Re-measure after a small delay in case DOM is still settling
    const timer = setTimeout(measure, 100)
    return () => clearTimeout(timer)
  }, [step, visible, currentStep])

  const completeTour = useCallback(() => {
    setVisible(false)
    localStorage.setItem(TOUR_DONE_KEY, '1')
    onComplete?.()
  }, [onComplete])

  function handleNext() {
    if (step < FIRST_RUN_TOUR.length - 1) {
      setStep(s => s + 1)
    } else {
      completeTour()
    }
  }

  function handlePrev() {
    if (step > 0) setStep(s => s - 1)
  }

  if (!visible) return null

  const tooltipStyle = targetRect
    ? computeTooltipStyle(targetRect, currentStep.side)
    : { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }

  const isFirst = step === 0
  const isLast = step === FIRST_RUN_TOUR.length - 1

  return (
    <>
      {/* Dim overlay */}
      <div className="fixed inset-0 bg-black/30 pointer-events-none z-40" />

      {/* Highlight box around target */}
      {targetRect && (
        <div
          className="fixed border-2 border-[var(--accent)] rounded-lg z-50 pointer-events-none transition-all duration-200"
          style={{
            top: targetRect.top - 4,
            left: targetRect.left - 4,
            width: targetRect.width + 8,
            height: targetRect.height + 8,
          }}
        />
      )}

      {/* Tooltip card */}
      <div
        className="fixed z-50 bg-[var(--surface-elevated,#1e1e2e)] border border-[var(--border)] rounded-xl p-4 shadow-xl w-72 pointer-events-auto"
        style={tooltipStyle}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-2">
          <h3 className="text-sm font-semibold text-[var(--text-primary)] leading-tight pr-2">
            {currentStep.title}
          </h3>
          <button
            onClick={completeTour}
            className="flex-shrink-0 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            aria-label="Skip tour"
          >
            <X size={14} />
          </button>
        </div>

        {/* Content */}
        <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-4">
          {currentStep.content}
        </p>

        {/* Progress dots */}
        <div className="flex items-center gap-1.5 mb-3">
          {FIRST_RUN_TOUR.map((_, i) => (
            <div
              key={i}
              className={`h-1.5 rounded-full transition-all duration-200 ${
                i === step
                  ? 'w-4 bg-[var(--accent)]'
                  : i < step
                  ? 'w-1.5 bg-[var(--accent)]/50'
                  : 'w-1.5 bg-[var(--border)]'
              }`}
            />
          ))}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between">
          <button
            onClick={handlePrev}
            disabled={isFirst}
            className="btn btn-sm btn-secondary flex items-center gap-1 disabled:opacity-30"
          >
            <ArrowLeft size={12} /> Prev
          </button>

          <button
            onClick={completeTour}
            className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            Skip tour
          </button>

          <button
            onClick={handleNext}
            className="btn btn-sm btn-primary flex items-center gap-1"
          >
            {isLast ? 'Finish' : 'Next'}
            {!isLast && <ArrowRight size={12} />}
          </button>
        </div>
      </div>
    </>
  )
}

// ── useTour hook ───────────────────────────────────────────────────────────────

export function useTour() {
  const [show, setShow] = useState(false)
  const startTour = () => setShow(true)
  const doneTour = () => setShow(false)
  return { show, startTour, doneTour }
}
