export function shouldRetryRequest(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false

  const message =
    error instanceof Error
      ? error.message.toLowerCase()
      : String(error ?? '').toLowerCase()

  if (!message) return failureCount < 2
  if (message.includes('cannot reach the draco backend')) return true
  if (message.includes('timed out')) return true
  if (message.includes('status 502') || message.includes('status 503') || message.includes('status 504')) {
    return true
  }
  if (message.includes('status 4')) return false
  return failureCount < 2
}
