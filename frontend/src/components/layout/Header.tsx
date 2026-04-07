import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Search, Plus, RefreshCw } from 'lucide-react'
import { useProjectStore } from '@/stores/useProjectStore'
import { useJobStore } from '@/stores/useJobStore'
import { useAssetStore } from '@/stores/useAssetStore'

interface HeaderProps {
  title?: string
  actions?: ReactNode
}

export function Header({ title, actions }: HeaderProps) {
  const projects = useProjectStore((s) => s.projects)
  const activeProjectId = useProjectStore((s) => s.activeProjectId)
  const activeProject = useProjectStore((s) => s.activeProject)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)
  const activeJobs = useJobStore((s) => s.getActiveJobs())
  const setFilter = useAssetStore((s) => s.setFilter)
  const [searchVal, setSearchVal] = useState('')

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setSearchVal(val)
    setFilter('search', val || undefined)
  }

  const hasActiveJobs = activeJobs.length > 0
  const leadJob = activeJobs[0] ?? null
  const jobSummary = activeJobs
    .map((job) => {
      const progressSuffix = Number.isFinite(job.progress) ? ` (${job.progress}%)` : ''
      return job.message || `${job.type} ${job.status}${progressSuffix}`
    })
    .join('\n')

  return (
    <header
      className="flex items-center gap-3 px-4 border-b border-border bg-surface shrink-0"
      style={{ height: 'var(--header-height)' }}
    >
      {/* Title */}
      <div className="flex-shrink-0 min-w-0">
        <h1 className="text-sm font-semibold text-text-primary">
          {title ?? activeProject?.name ?? 'Draco Studio'}
        </h1>
      </div>

      {projects.length > 0 && (
        <select
          value={activeProjectId ?? ''}
          onChange={(e) => setActiveProject(e.target.value || null)}
          className="text-xs py-1.5 px-2 max-w-[220px]"
          title="Active project"
        >
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      )}

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
              placeholder="Search assets..."
              className="pl-8 pr-3 py-1.5 text-xs"
              style={{ background: 'var(--background)' }}
            />
          </div>
        </div>
      )}

      {!activeProject && projects.length === 0 && (
        <Link to="/settings" className="btn btn-secondary btn-sm">
          <Plus size={13} />
          Create Project
        </Link>
      )}

      <div className="flex-1" />

      {/* Job indicator */}
      {hasActiveJobs && (
        <div
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent/15 border border-accent/30 text-accent text-xs font-medium"
          title={jobSummary}
        >
          <RefreshCw size={12} className="animate-spin" />
          <span>
            {activeJobs.length} job{activeJobs.length > 1 ? 's' : ''} running
            {leadJob && Number.isFinite(leadJob.progress) ? ` - ${leadJob.progress}%` : ''}
            {leadJob?.message ? ` - ${leadJob.message}` : ''}
          </span>
        </div>
      )}

      {/* Actions slot */}
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  )
}
