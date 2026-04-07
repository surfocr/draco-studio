import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Project } from '@/types/api'

interface ProjectState {
  projects: Project[]
  activeProjectId: string | null

  setProjects: (projects: Project[]) => void
  setActiveProject: (id: string | null) => void
  updateProject: (project: Project) => void
  addProject: (project: Project) => void
  removeProject: (id: string) => void

  get activeProject(): Project | null
}

function normalizeActiveProjectId(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

export const useProjectStore = create<ProjectState>()(
  persist(
    (set, get) => ({
      projects: [],
      activeProjectId: null,

      setProjects: (projects) =>
        set((s) => {
          const hasActiveProject = !!s.activeProjectId && projects.some((p) => p.id === s.activeProjectId)
          return {
            projects,
            activeProjectId: hasActiveProject
              ? s.activeProjectId
              : (projects[0]?.id ?? null),
          }
        }),
      setActiveProject: (id) => set({ activeProjectId: normalizeActiveProjectId(id) }),
      updateProject: (project) =>
        set((s) => ({
          projects: s.projects.map((p) => (p.id === project.id ? project : p)),
        })),
      addProject: (project) =>
        set((s) => ({
          projects: [project, ...s.projects.filter((existing) => existing.id !== project.id)],
          activeProjectId: s.activeProjectId ?? project.id,
        })),
      removeProject: (id) =>
        set((s) => ({
          projects: s.projects.filter((p) => p.id !== id),
          activeProjectId:
            s.activeProjectId === id
              ? (s.projects.filter((p) => p.id !== id)[0]?.id ?? null)
              : s.activeProjectId,
        })),

      get activeProject() {
        const { projects, activeProjectId } = get()
        return projects.find((p) => p.id === activeProjectId) ?? null
      },
    }),
    {
      name: 'draco-project',
      version: 2,
      partialize: (state) => ({ activeProjectId: state.activeProjectId }),
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
