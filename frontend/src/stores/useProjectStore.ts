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

export const useProjectStore = create<ProjectState>()(
  persist(
    (set, get) => ({
      projects: [],
      activeProjectId: null,

      setProjects: (projects) => set({ projects }),
      setActiveProject: (id) => set({ activeProjectId: id }),
      updateProject: (project) =>
        set((s) => ({
          projects: s.projects.map((p) => (p.id === project.id ? project : p)),
        })),
      addProject: (project) =>
        set((s) => ({ projects: [project, ...s.projects] })),
      removeProject: (id) =>
        set((s) => ({
          projects: s.projects.filter((p) => p.id !== id),
          activeProjectId: s.activeProjectId === id ? null : s.activeProjectId,
        })),

      get activeProject() {
        const { projects, activeProjectId } = get()
        return projects.find((p) => p.id === activeProjectId) ?? null
      },
    }),
    { name: 'draco-project' }
  )
)
