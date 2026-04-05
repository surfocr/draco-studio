import React, { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AppShell } from '@/components/layout/AppShell'
import { ThemeProvider } from '@/components/providers/ThemeProvider'
import { ToastProvider } from '@/components/providers/ToastProvider'
import { Dashboard } from '@/views/Dashboard'
import { Gallery } from '@/views/Gallery'
import { Captions } from '@/views/Captions'
import { Faces } from '@/views/Faces'
import { Ranking } from '@/views/Ranking'
import { Coach } from '@/views/Coach'
import { Augmentation } from '@/views/Augmentation'
import { Export } from '@/views/Export'
import { Settings } from '@/views/Settings'
import Benchmark from '@/views/Benchmark'
import { Duplicates } from '@/views/Duplicates'
import Search from '@/views/Search'
import { AutoSort } from '@/views/AutoSort'
import { jobsApi } from '@/hooks/useApi'
import { useJobStore } from '@/stores/useJobStore'

function JobPoller() {
  const setJobs = useJobStore((s) => s.setJobs)

  const { data } = useQuery({
    queryKey: ['jobs-poll'],
    queryFn: jobsApi.list,
    refetchInterval: 3000,
  })

  useEffect(() => {
    if (data) setJobs(data)
  }, [data, setJobs])

  return null
}

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <BrowserRouter>
          <JobPoller />
          <Routes>
            <Route path="/" element={<AppShell />}>
              <Route index element={<Navigate to="/gallery" replace />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="gallery" element={<Gallery />} />
              <Route path="captions" element={<Captions />} />
              <Route path="faces" element={<Faces />} />
              <Route path="ranking" element={<Ranking />} />
              <Route path="coach" element={<Coach />} />
              <Route path="augmentation" element={<Augmentation />} />
              <Route path="export" element={<Export />} />
              <Route path="settings" element={<Settings />} />
              <Route path="benchmark" element={<Benchmark />} />
              <Route path="duplicates" element={<Duplicates />} />
              <Route path="search" element={<Search />} />
              <Route path="autosort" element={<AutoSort />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </ThemeProvider>
  )
}
