import React from 'react'

// Dark theme is the only theme. This provider exists for future extensibility.
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
