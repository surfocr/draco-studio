import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Project } from '@/types/api'

interface ProjectState {
  projects: Project[]
  activeProjectId: string | null
  activeProject: Project | null

  setProjects: (projects: Project[]) => void
  setActiveProject: (id: string | null) => void
  updateProject: (project: Project) => void
  addProject: (project: Project) => void
  removeProject: (id: string) => void
}

function normalizeActiveProjectId(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function deriveActiveProject(
  projects: Project[],
  activeProjectId: string | null
): Project | null {
  if (!activeProjectId) return null
  return projects.find((p) => p.id === activeProjectId) ?? null
}

export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      projects: [],
      activeProjectId: null,
      activeProject: null,

      // `activeProject` is intentionally stored as a data field rather than
      // a getter: Zustand's setState does Object.assign({}, oldState, patch),
      // which invokes getter accessors eagerly and turns them into stale
      // data properties on the next state. Every setter recomputes
      // activeProject explicitly instead.
      setProjects: (projects) =>
        set((s) => {
          const hasActive = !!s.activeProjectId && projects.some((p) => p.id === s.activeProjectId)
          const activeProjectId = hasActive ? s.activeProjectId : (projects[0]?.id ?? null)
          return {
            projects,
            activeProjectId,
            activeProject: deriveActiveProject(projects, activeProjectId),
          }
        }),
      setActiveProject: (id) =>
        set((s) => {
          const activeProjectId = normalizeActiveProjectId(id)
          return {
            activeProjectId,
            activeProject: deriveActiveProject(s.projects, activeProjectId),
          }
        }),
      updateProject: (project) =>
        set((s) => {
          const projects = s.projects.map((p) => (p.id === project.id ? project : p))
          return {
            projects,
            activeProject: deriveActiveProject(projects, s.activeProjectId),
          }
        }),
      addProject: (project) =>
        set((s) => {
          const projects = [project, ...s.projects.filter((existing) => existing.id !== project.id)]
          const activeProjectId = s.activeProjectId ?? project.id
          return {
            projects,
            activeProjectId,
            activeProject: deriveActiveProject(projects, activeProjectId),
          }
        }),
      removeProject: (id) =>
        set((s) => {
          const projects = s.projects.filter((p) => p.id !== id)
          const activeProjectId =
            s.activeProjectId === id ? (projects[0]?.id ?? null) : s.activeProjectId
          return {
            projects,
            activeProjectId,
            activeProject: deriveActiveProject(projects, activeProjectId),
          }
        }),
    }),
    {
      name: 'draco-project',
      version: 2,
      partialize: (state) => ({ activeProjectId: state.activeProjectId }),
      merge: (persistedState, currentState) => {
        const persisted = persistedState as Partial<ProjectState> | undefined
        const activeProjectId =
          persisted && 'activeProjectId' in persisted
            ? normalizeActiveProjectId(persisted.activeProjectId)
            : currentState.activeProjectId
        return {
          ...currentState,
          activeProjectId,
          activeProject: deriveActiveProject(currentState.projects, activeProjectId),
        }
      },
    }
  )
)
