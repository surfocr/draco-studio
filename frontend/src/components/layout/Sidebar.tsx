import React from 'react'
import { NavLink } from 'react-router-dom'
import { clsx } from 'clsx'
import {
  Images,
  Brain,
  Users,
  Trophy,
  Lightbulb,
  Wand2,
  Download,
  Settings,
  ChevronLeft,
  ChevronRight,
  Zap,
  BarChart2,
  Layers,
  Search,
  LayoutDashboard,
  SlidersHorizontal,
} from 'lucide-react'
import { useAppStore } from '@/stores/useAppStore'
import { useProjectStore } from '@/stores/useProjectStore'

const NAV_ITEMS = [
  { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/gallery', label: 'Gallery', icon: Images },
  { path: '/faces', label: 'Faces', icon: Users },
  { path: '/captions', label: 'Captions', icon: Brain },
  { path: '/ranking', label: 'Ranking', icon: Trophy },
  { path: '/coach', label: 'Coach', icon: Lightbulb },
  { path: '/augmentation', label: 'Augment', icon: Wand2 },
  { path: '/export', label: 'Export', icon: Download },
  { path: '/benchmark', label: 'Benchmark', icon: BarChart2 },
  { path: '/duplicates', label: 'Duplicates', icon: Layers },
  { path: '/search', label: 'Search', icon: Search },
  { path: '/autosort', label: 'Auto-Sort', icon: SlidersHorizontal },
]

function ProjectSelector() {
  const projects = useProjectStore((s) => s.projects)
  const activeProject = useProjectStore((s) => s.activeProject)
  const setActiveProject = useProjectStore((s) => s.setActiveProject)

  if (projects.length === 0) {
    return (
      <div className="mx-2 mt-2 mb-1 px-2 py-1.5 rounded-md bg-surface-elevated border border-border">
        <NavLink to="/settings" className="text-xs text-accent hover:underline">
          + Create a project
        </NavLink>
      </div>
    )
  }

  return (
    <div className="mx-2 mt-2 mb-1">
      <select
        value={activeProject?.id ?? ''}
        onChange={(e) => setActiveProject(e.target.value || null)}
        className="w-full bg-surface-elevated border border-border rounded-md px-2 py-1.5 text-sm text-text-primary truncate focus:outline-none focus:border-accent"
      >
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} ({p.asset_count})
          </option>
        ))}
      </select>
    </div>
  )
}

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar } = useAppStore()
  const activeProject = useProjectStore((s) => s.activeProject)

  return (
    <aside
      style={{
        width: sidebarCollapsed ? 'var(--sidebar-collapsed-width)' : 'var(--sidebar-width)',
        flexShrink: 0,
        transition: 'width 0.2s ease',
      }}
      className="flex flex-col bg-surface border-r border-border h-full relative"
    >
      {/* Logo / brand */}
      <div
        className={clsx(
          'flex items-center gap-3 px-3 border-b border-border',
          'overflow-hidden'
        )}
        style={{ height: 'var(--header-height)', minHeight: 'var(--header-height)' }}
      >
        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-accent flex items-center justify-center">
          <Zap size={16} className="text-white" />
        </div>
        {!sidebarCollapsed && (
          <div className="min-w-0">
            <div className="text-sm font-semibold text-text-primary truncate">Draco Studio</div>
            <div className="text-xs text-text-secondary truncate">v6.0</div>
          </div>
        )}
      </div>

      {/* Project selector */}
      {!sidebarCollapsed && (
        <ProjectSelector />
      )}

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2 px-1.5">
        {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
          <NavLink
            key={path}
            to={path}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-2.5 py-2 rounded-md mb-0.5',
                'text-sm transition-colors',
                isActive
                  ? 'bg-accent/20 text-accent font-medium'
                  : 'text-text-secondary hover:bg-surface-elevated hover:text-text-primary'
              )
            }
          >
            <Icon size={16} className="flex-shrink-0" />
            {!sidebarCollapsed && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Bottom: settings */}
      <div className="p-1.5 border-t border-border">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            clsx(
              'flex items-center gap-3 px-2.5 py-2 rounded-md',
              'text-sm transition-colors',
              isActive
                ? 'bg-accent/20 text-accent'
                : 'text-text-secondary hover:bg-surface-elevated hover:text-text-primary'
            )
          }
        >
          <Settings size={16} className="flex-shrink-0" />
          {!sidebarCollapsed && <span>Settings</span>}
        </NavLink>
      </div>

      {/* Collapse toggle */}
      <button
        onClick={toggleSidebar}
        className={clsx(
          'absolute -right-3 top-1/2 -translate-y-1/2',
          'w-6 h-6 rounded-full bg-surface-elevated border border-border',
          'flex items-center justify-center',
          'hover:bg-accent hover:border-accent hover:text-white',
          'transition-all text-text-secondary z-10'
        )}
      >
        {sidebarCollapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
      </button>
    </aside>
  )
}
