import { beforeEach, describe, expect, it } from 'vitest'
import { useJobStore } from './useJobStore'

describe('useJobStore', () => {
  beforeEach(() => {
    useJobStore.setState({ jobs: {}, activeJobIds: [] })
  })

  it('tracks only pending and running jobs as active', () => {
    useJobStore.getState().addJob({
      id: 'job-pending',
      type: 'duplicate_scan',
      status: 'pending',
      progress: 0,
      message: 'Queued',
      result: null,
      error: null,
      created_at: '2026-01-01T00:00:00Z',
      started_at: null,
      finished_at: null,
    })

    useJobStore.getState().addJob({
      id: 'job-done',
      type: 'export_lora',
      status: 'done',
      progress: 100,
      message: 'Done',
      result: null,
      error: null,
      created_at: '2026-01-01T00:00:00Z',
      started_at: '2026-01-01T00:00:01Z',
      finished_at: '2026-01-01T00:00:02Z',
    })

    expect(useJobStore.getState().activeJobIds).toEqual(['job-pending'])
  })

  it('removes jobs from the active list when they become terminal', () => {
    useJobStore.getState().addJob({
      id: 'job-running',
      type: 'ingest_upload',
      status: 'running',
      progress: 50,
      message: 'Running',
      result: null,
      error: null,
      created_at: '2026-01-01T00:00:00Z',
      started_at: '2026-01-01T00:00:01Z',
      finished_at: null,
    })

    useJobStore.getState().updateJob('job-running', { status: 'done', progress: 100 })

    expect(useJobStore.getState().activeJobIds).toEqual([])
    expect(useJobStore.getState().jobs['job-running']?.status).toBe('done')
  })
})
