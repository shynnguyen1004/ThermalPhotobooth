import { useCallback, useEffect, useRef, useState } from 'react'

const HOLD_MS = 1000

type Options = {
  disabled: boolean
  onShortPress: () => void
  onLongPressComplete: () => void
}

function getAudioContext(existing: AudioContext | null): AudioContext | null {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    if (!Ctx) return existing
    const ctx = existing ?? new Ctx()
    void ctx.resume()
    return ctx
  } catch {
    return existing
  }
}

/** Safari iOS does not implement navigator.vibrate — use audio ticks instead. */
function canUseHardwareVibration(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function'
}

function playHoldTick(audioCtx: AudioContext | null, step: number): AudioContext | null {
  const ctx = getAudioContext(audioCtx)
  if (!ctx) return audioCtx
  try {
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = 'triangle'
    osc.connect(gain)
    gain.connect(ctx.destination)
    const t = ctx.currentTime
    const freq = 90 + step * 14
    const vol = Math.min(0.1 + step * 0.025, 0.32)
    osc.frequency.setValueAtTime(freq, t)
    gain.gain.setValueAtTime(vol, t)
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.045)
    osc.start(t)
    osc.stop(t + 0.045)
    return ctx
  } catch {
    return ctx
  }
}

function playUnlockPop(audioCtx: AudioContext | null): AudioContext | null {
  const ctx = getAudioContext(audioCtx)
  if (!ctx) return audioCtx
  try {
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = 'sine'
    osc.connect(gain)
    gain.connect(ctx.destination)
    const t = ctx.currentTime
    osc.frequency.setValueAtTime(220, t)
    osc.frequency.exponentialRampToValueAtTime(680, t + 0.075)
    gain.gain.setValueAtTime(0.42, t)
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.15)
    osc.start(t)
    osc.stop(t + 0.15)
    if (canUseHardwareVibration()) {
      navigator.vibrate([0, 35, 45, 55])
    }
    return ctx
  } catch {
    return ctx
  }
}

export function useReprintLastGesture({ disabled, onShortPress, onLongPressComplete }: Options) {
  const [holding, setHolding] = useState(false)
  const [progress, setProgress] = useState(0)

  const holdStartRef = useRef(0)
  const completedRef = useRef(false)
  const timerRef = useRef<number | null>(null)
  const pulseRef = useRef<number | null>(null)
  const rafRef = useRef<number | null>(null)
  const pulseStepRef = useRef(0)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const vibrateSupportedRef = useRef(canUseHardwareVibration())

  const clearHold = useCallback(() => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    if (pulseRef.current !== null) window.clearInterval(pulseRef.current)
    if (rafRef.current !== null) window.cancelAnimationFrame(rafRef.current)
    timerRef.current = null
    pulseRef.current = null
    rafRef.current = null
    pulseStepRef.current = 0
    setHolding(false)
    setProgress(0)
  }, [])

  useEffect(() => () => clearHold(), [clearHold])

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (disabled) return
      e.preventDefault()
      e.currentTarget.setPointerCapture(e.pointerId)

      completedRef.current = false
      holdStartRef.current = Date.now()
      setHolding(true)
      setProgress(0)
      pulseStepRef.current = 0
      audioCtxRef.current = getAudioContext(audioCtxRef.current)

      const useVibrate = vibrateSupportedRef.current

      pulseRef.current = window.setInterval(() => {
        pulseStepRef.current += 1
        const step = pulseStepRef.current
        if (useVibrate) {
          const ms = Math.min(15 + step * 8, 110)
          navigator.vibrate(ms)
        } else {
          // iOS / unsupported: rising tick sounds mimic haptic ramp
          audioCtxRef.current = playHoldTick(audioCtxRef.current, step)
        }
      }, 160)

      const tick = () => {
        const elapsed = Date.now() - holdStartRef.current
        setProgress(Math.min(1, elapsed / HOLD_MS))
        if (elapsed < HOLD_MS) {
          rafRef.current = window.requestAnimationFrame(tick)
        }
      }
      rafRef.current = window.requestAnimationFrame(tick)

      timerRef.current = window.setTimeout(() => {
        completedRef.current = true
        clearHold()
        audioCtxRef.current = playUnlockPop(audioCtxRef.current)
        onLongPressComplete()
      }, HOLD_MS)
    },
    [clearHold, disabled, onLongPressComplete],
  )

  const endHold = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (disabled) return
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        /* ignore */
      }
      const wasCompleted = completedRef.current
      const duration = Date.now() - holdStartRef.current
      clearHold()
      if (!wasCompleted && duration >= 80 && duration < HOLD_MS) {
        onShortPress()
      }
    },
    [clearHold, disabled, onShortPress],
  )

  const onPointerUp = endHold
  const onPointerCancel = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (disabled) return
      completedRef.current = false
      clearHold()
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        /* ignore */
      }
    },
    [clearHold, disabled],
  )

  return {
    holding,
    progress,
    hapticSupported: vibrateSupportedRef.current,
    onPointerDown,
    onPointerUp,
    onPointerCancel,
  }
}
