import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AppState {
  sidebarCollapsed: boolean
  theme: 'dark'
  activeView: string

  setSidebarCollapsed: (v: boolean) => void
  toggleSidebar: () => void
  setActiveView: (view: string) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      theme: 'dark',
      activeView: 'gallery',

      setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
      toggleSidebar: () =>
        set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setActiveView: (view) => set({ activeView: view }),
    }),
    { name: 'draco-app' }
  )
)
