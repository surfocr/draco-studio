import { useState } from 'react'
import { HelpCircle } from 'lucide-react'

interface TooltipProps {
  content: string
  children?: React.ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
  showIcon?: boolean
}

export function Tooltip({ content, children, side = 'top', showIcon = false }: TooltipProps) {
  const [visible, setVisible] = useState(false)

  const sideClasses = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  }

  return (
    <div
      className="relative inline-flex items-center"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      {children}
      {showIcon && (
        <HelpCircle size={12} className="text-zinc-500 hover:text-zinc-300 ml-1 cursor-help" />
      )}
      {visible && content && (
        <div className={`absolute z-50 ${sideClasses[side]} pointer-events-none`}>
          <div className="bg-zinc-800 border border-zinc-700 text-zinc-200 text-xs rounded-lg px-2.5 py-1.5 shadow-xl whitespace-nowrap max-w-64 break-words">
            {content}
          </div>
        </div>
      )}
    </div>
  )
}

/** Inline help icon with tooltip — use next to labels */
export function HelpTip({ text }: { text: string }) {
  return (
    <Tooltip content={text} side="top">
      <HelpCircle size={12} className="text-zinc-600 hover:text-zinc-400 cursor-help" />
    </Tooltip>
  )
}
