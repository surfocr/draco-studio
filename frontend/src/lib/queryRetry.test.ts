import { describe, expect, it } from 'vitest'
import { shouldRetryRequest } from './queryRetry'

describe('shouldRetryRequest', () => {
  it('retries transient backend connectivity failures', () => {
    expect(shouldRetryRequest(0, new Error('Cannot reach the Draco backend at http://127.0.0.1:18082.'))).toBe(true)
    expect(shouldRetryRequest(1, new Error('Request timed out. The backend may be busy or unavailable.'))).toBe(true)
    expect(shouldRetryRequest(1, new Error('Request failed with status 503'))).toBe(true)
  })

  it('does not retry client-side validation errors', () => {
    expect(shouldRetryRequest(0, new Error('Request failed with status 404'))).toBe(false)
    expect(shouldRetryRequest(0, new Error('Request failed with status 422'))).toBe(false)
  })

  it('stops retrying after the configured limit', () => {
    expect(shouldRetryRequest(2, new Error('Cannot reach the Draco backend.'))).toBe(false)
  })
})
