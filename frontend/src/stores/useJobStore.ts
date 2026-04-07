import { create } from 'zustand'
import type { Job } from '@/types/api'

function isActiveJob(job: Pick<Job, 'status'>): boolean {
  return job.status === 'running' || job.status === 'pending'
}

interface JobState {
  jobs: Record<string, Job>
  activeJobIds: string[]

  addJob: (job: Job) => void
  updateJob: (id: string, patch: Partial<Job>) => void
  removeJob: (id: string) => void
  setJobs: (jobs: Job[]) => void

  getActiveJobs: () => Job[]
  getJob: (id: string) => Job | undefined
}

export const useJobStore = create<JobState>()((set, get) => ({
  jobs: {},
  activeJobIds: [],

  addJob: (job) =>
    set((s) => ({
      jobs: { ...s.jobs, [job.id]: job },
      activeJobIds: isActiveJob(job)
        ? (s.activeJobIds.includes(job.id) ? s.activeJobIds : [...s.activeJobIds, job.id])
        : s.activeJobIds.filter((activeId) => activeId !== job.id),
    })),

  updateJob: (id, patch) =>
    set((s) => {
      if (!s.jobs[id]) return s
      const nextJob = { ...s.jobs[id], ...patch }
      return {
        jobs: { ...s.jobs, [id]: nextJob },
        activeJobIds: isActiveJob(nextJob)
          ? (s.activeJobIds.includes(id) ? s.activeJobIds : [...s.activeJobIds, id])
          : s.activeJobIds.filter((activeId) => activeId !== id),
      }
    }),

  removeJob: (id) =>
    set((s) => {
      const next = { ...s.jobs }
      delete next[id]
      return { jobs: next, activeJobIds: s.activeJobIds.filter((j) => j !== id) }
    }),

  setJobs: (jobs) =>
    set({
      jobs: Object.fromEntries(jobs.map((j) => [j.id, j])),
      activeJobIds: jobs.filter(isActiveJob).map((j) => j.id),
    }),

  getActiveJobs: () => {
    const { jobs, activeJobIds } = get()
    return activeJobIds.map((id) => jobs[id]).filter(Boolean)
  },

  getJob: (id) => get().jobs[id],
}))
