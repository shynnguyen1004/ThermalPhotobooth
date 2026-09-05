import { useCallback, useRef, useState } from 'react'
import { fetchCaptureProgress } from '../api/client'
import { toPhaseOverlay } from '../components/CaptureOverlay'
import type { CaptureOverlayState, CapturePhase } from '../types'

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

export function useCaptureOverlay() {
  const [overlay, setOverlay] = useState<CaptureOverlayState>(null)
  const pollRef = useRef<number | null>(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startPolling = useCallback(() => {
    stopPolling()
    pollRef.current = window.setInterval(() => {
      void fetchCaptureProgress().then((progress) => {
        const phase = (progress.phase || 'idle') as CapturePhase | string
        if (phase === 'idle' || phase === 'countdown') return
        // Keep advancing through backend phases until capture request finishes.
        setOverlay(toPhaseOverlay(phase, progress.label))
      })
    }, 180)
  }, [stopPolling])

  const runCountdown = useCallback(async () => {
    for (const count of [3, 2, 1] as const) {
      setOverlay({ mode: 'countdown', count })
      await sleep(1000)
    }
  }, [])

  const showPhase = useCallback((phase: CapturePhase, label?: string) => {
    setOverlay(toPhaseOverlay(phase, label))
  }, [])

  const clearOverlay = useCallback(
    (delayMs = 0) => {
      stopPolling()
      if (delayMs <= 0) {
        setOverlay(null)
        return
      }
      window.setTimeout(() => setOverlay(null), delayMs)
    },
    [stopPolling],
  )

  return {
    overlay,
    setOverlay,
    runCountdown,
    startPolling,
    stopPolling,
    showPhase,
    clearOverlay,
  }
}
