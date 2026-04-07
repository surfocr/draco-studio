import { it, expect, vi } from 'vitest'
it('check localStorage', () => {
  console.log('typeof globalThis.localStorage:', typeof globalThis.localStorage)
  console.log('globalThis.localStorage:', globalThis.localStorage)
  const mock = { getItem: () => null, setItem: () => {}, removeItem: () => {} }
  vi.stubGlobal('localStorage', mock)
  console.log('after stub:', globalThis.localStorage === mock)
  console.log('typeof window.localStorage:', typeof window?.localStorage)
})
