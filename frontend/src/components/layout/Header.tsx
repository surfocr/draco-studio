import React, { useState } from 'react'
import { Search, Plus, Activity, RefreshCw } from 'lucide-react'
import { clsx } from 'clsx'
import { useProjectStore } from '@/stores/useProjectStore'
import { useJobStore } from '@/stores/useJobStore'
import { useAssetStore } from '@/stores/useAssetStore'

interface HeaderProps {
  title?: string
  actions?: React.ReactNode
}

export function Header({ title, actions }: HeaderProps) {
  const activeProject = useProjectStore((s) => s.activeProject)
  const activeJobs = useJobStore((s) => s.getActiveJobs())
  const setFilter = useAssetStore((s) => s.setFilter)
  const [searchVal, setSearchVal] = useState('')

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setSearchVal(val)
    setFilter('search', val || undefined)
  }

  const hasActiveJobs = activeJobs.length > 0

  return (
    <header
      className="flex items-center gap-3 px-4 border-b border-border bg-surface shrink-0"
      style={{ height: 'var(--header-height)' }}
    >
      {/* Title */}
      <div className="flex-shrink-0">
        <h1 className="text-sm font-semibold text-text-primary">
          {title ?? activeProject?.name ?? 'Draco Studio'}
        </h1>
      </div>

      {/* Search */}
      {activeProject && (
        <div className="flex items-center gap-2 flex-1 max-w-sm">
          <div className="relative flex-1">
            <Search
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none"
            />
            <input
              value={searchVal}
              onChange={handleSearch}
              placeholder="Search assets…"
              className="pl-8 pr-3 py-1.5 text-xs"
              style={{ background: 'var(--background)' }}
            />
          </div>
        </div>
      )}

      <div className="flex-1" />

      {/* Job indicator */}
      {hasActiveJobs && (
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent/15 border border-accent/30 text-accent text-xs font-medium">
          <RefreshCw size={12} className="animate-spin" />
          <span>{activeJobs.length} job{activeJobs.length > 1 ? 's' : ''} running</span>
        </div>
      )}

      {/* Actions slot */}
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  )
}
