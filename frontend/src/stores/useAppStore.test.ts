import { beforeEach, describe, expect, it, vi } from 'vitest'

let useAppStore: typeof import('./useAppStore').useAppStore

describe('useAppStore', () => {
  beforeEach(async () => {
    vi.resetModules()
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    })
    ;({ useAppStore } = await import('./useAppStore'))
    useAppStore.setState({ sidebarCollapsed: false, activeView: 'gallery' })
  })

  it('starts with sidebar expanded and gallery view', () => {
    const state = useAppStore.getState()
    expect(state.sidebarCollapsed).toBe(false)
    expect(state.activeView).toBe('gallery')
    expect(state.theme).toBe('dark')
  })

  it('setSidebarCollapsed sets the value directly', () => {
    useAppStore.getState().setSidebarCollapsed(true)
    expect(useAppStore.getState().sidebarCollapsed).toBe(true)

    useAppStore.getState().setSidebarCollapsed(false)
    expect(useAppStore.getState().sidebarCollapsed).toBe(false)
  })

  it('toggleSidebar flips the collapsed state', () => {
    useAppStore.setState({ sidebarCollapsed: false })
    useAppStore.getState().toggleSidebar()
    expect(useAppStore.getState().sidebarCollapsed).toBe(true)

    useAppStore.getState().toggleSidebar()
    expect(useAppStore.getState().sidebarCollapsed).toBe(false)
  })

  it('setActiveView updates the active view', () => {
    useAppStore.getState().setActiveView('coach')
    expect(useAppStore.getState().activeView).toBe('coach')

    useAppStore.getState().setActiveView('ranking')
    expect(useAppStore.getState().activeView).toBe('ranking')
  })

  it('toggleSidebar is independent of setActiveView', () => {
    useAppStore.getState().setActiveView('export')
    useAppStore.getState().toggleSidebar()

    expect(useAppStore.getState().activeView).toBe('export')
    expect(useAppStore.getState().sidebarCollapsed).toBe(true)
  })
})
