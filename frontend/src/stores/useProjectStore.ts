import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
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

function deriveActiveProject(projects: Project[], activeProjectId: string | null): Project | null {
  return projects.find((p) => p.id === activeProjectId) ?? null
}

export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      projects: [],
      activeProjectId: null,
      activeProject: null,

      setProjects: (projects) =>
        set((s) => {
          const hasActiveProject = !!s.activeProjectId && projects.some((p) => p.id === s.activeProjectId)
          const activeProjectId = hasActiveProject ? s.activeProjectId : (projects[0]?.id ?? null)
          return {
            projects,
            activeProjectId,
            activeProject: deriveActiveProject(projects, activeProjectId),
          }
        }),
      setActiveProject: (id) => {
        const activeProjectId = normalizeActiveProjectId(id)
        set((s) => ({ activeProjectId, activeProject: deriveActiveProject(s.projects, activeProjectId) }))
      },
      updateProject: (project) =>
        set((s) => ({
          projects: s.projects.map((p) => (p.id === project.id ? project : p)),
          activeProject: s.activeProjectId === project.id ? project : s.activeProject,
        })),
      addProject: (project) =>
        set((s) => {
          const projects = [project, ...s.projects.filter((existing) => existing.id !== project.id)]
          const activeProjectId = s.activeProjectId ?? project.id
          return { projects, activeProjectId, activeProject: deriveActiveProject(projects, activeProjectId) }
        }),
      removeProject: (id) =>
        set((s) => {
          const projects = s.projects.filter((p) => p.id !== id)
          const activeProjectId =
            s.activeProjectId === id ? (projects[0]?.id ?? null) : s.activeProjectId
          return { projects, activeProjectId, activeProject: deriveActiveProject(projects, activeProjectId) }
        }),
    }),
    {
      name: 'draco-project',
      version: 2,
      storage: createJSONStorage(() => globalThis.localStorage),
      partialize: (state) => ({ activeProjectId: state.activeProjectId }),
      migrate: (persistedState: unknown, version: number) => {
        if (version < 2) {
          const legacy = persistedState as Record<string, unknown> | undefined
          return { activeProjectId: normalizeActiveProjectId(legacy?.activeProjectId) }
        }
        return persistedState
      },
      merge: (persistedState, currentState) => {
        const persisted = persistedState as Partial<ProjectState> | undefined
        return {
          ...currentState,
          activeProjectId:
            persisted && 'activeProjectId' in persisted
              ? normalizeActiveProjectId(persisted.activeProjectId)
              : currentState.activeProjectId,
        }
      },
    }
  )
)
