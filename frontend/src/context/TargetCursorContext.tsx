import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'photobooth-target-cursor'

type TargetCursorContextValue = {
  enabled: boolean
  setEnabled: (enabled: boolean) => void
  toggle: () => void
}

const TargetCursorContext = createContext<TargetCursorContextValue | null>(null)

function readStoredEnabled(): boolean {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === null) return true
    return stored === 'true'
  } catch {
    return true
  }
}

export function TargetCursorProvider({ children }: { children: ReactNode }) {
  const [enabled, setEnabled] = useState(readStoredEnabled)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(enabled))
    } catch {
      /* ignore quota / private mode */
    }
  }, [enabled])

  const toggle = useCallback(() => {
    setEnabled((on) => !on)
  }, [])

  const value = useMemo(
    () => ({ enabled, setEnabled, toggle }),
    [enabled, toggle],
  )

  return <TargetCursorContext.Provider value={value}>{children}</TargetCursorContext.Provider>
}

export function useTargetCursor() {
  const ctx = useContext(TargetCursorContext)
  if (!ctx) {
    throw new Error('useTargetCursor must be used within TargetCursorProvider')
  }
  return ctx
}
