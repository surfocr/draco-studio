import { create } from 'zustand'
import type { Job } from '@/types/api'

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
      activeJobIds: s.activeJobIds.includes(job.id)
        ? s.activeJobIds
        : [...s.activeJobIds, job.id],
    })),

  updateJob: (id, patch) =>
    set((s) => ({
      jobs: s.jobs[id]
        ? { ...s.jobs, [id]: { ...s.jobs[id], ...patch } }
        : s.jobs,
    })),

  removeJob: (id) =>
    set((s) => {
      const next = { ...s.jobs }
      delete next[id]
      return { jobs: next, activeJobIds: s.activeJobIds.filter((j) => j !== id) }
    }),

  setJobs: (jobs) =>
    set({
      jobs: Object.fromEntries(jobs.map((j) => [j.id, j])),
      activeJobIds: jobs
        .filter((j) => j.status === 'running' || j.status === 'pending')
        .map((j) => j.id),
    }),

  getActiveJobs: () => {
    const { jobs, activeJobIds } = get()
    return activeJobIds.map((id) => jobs[id]).filter(Boolean)
  },

  getJob: (id) => get().jobs[id],
}))
