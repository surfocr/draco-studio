import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { jobsApi } from './useApi'
import { useJobStore } from '@/stores/useJobStore'

/** Poll all active jobs every 2s and keep the store in sync. */
export function useJobPolling(enabled = true) {
  const setJobs = useJobStore((s) => s.setJobs)
  const updateJob = useJobStore((s) => s.updateJob)

  useQuery({
    queryKey: ['jobs'],
    queryFn: async () => {
      const jobs = await jobsApi.list()
      setJobs(jobs)
      return jobs
    },
    refetchInterval: enabled ? 2000 : false,
    enabled,
  })
}

/** Subscribe to a single job via WebSocket for real-time updates. */
export function useJobWebSocket(jobId: string | null) {
  const updateJob = useJobStore((s) => s.updateJob)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!jobId) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const ws = new WebSocket(`${protocol}//${host}/api/jobs/ws/${jobId}`)
    wsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        updateJob(jobId, data)
      } catch {
        // ignore parse errors
      }
    }

    ws.onerror = () => {
      // WebSocket failed; fall back to polling (handled by useJobPolling)
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [jobId, updateJob])
}
