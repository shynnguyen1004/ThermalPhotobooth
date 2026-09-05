import type { CaptureOverlayState, CapturePhase } from '../types'

const PHASE_LABELS: Record<string, string> = {
  capturing: 'Capturing…',
  processing: 'Processing…',
  linking: 'Creating link…',
  uploading: 'Uploading…',
  printing: 'Printing…',
  done: 'Done',
  error: 'Something went wrong',
}

export function phaseLabel(phase: string, label?: string): string {
  if (label && label.trim()) return label
  return PHASE_LABELS[phase] || phase
}

type CaptureOverlayProps = {
  state: CaptureOverlayState
}

export function CaptureOverlay({ state }: CaptureOverlayProps) {
  if (!state) return null

  if (state.mode === 'countdown') {
    return (
      <div className="capture-overlay" role="status" aria-live="assertive">
        <div className="capture-overlay__countdown" key={state.count}>
          {state.count}
        </div>
        <p className="capture-overlay__hint">Get ready</p>
      </div>
    )
  }

  const tone =
    state.phase === 'done' ? 'is-ok' : state.phase === 'error' ? 'is-err' : 'is-busy'

  return (
    <div className={`capture-overlay ${tone}`} role="status" aria-live="polite">
      <p className="capture-overlay__phase">{state.label}</p>
      {state.phase !== 'done' && state.phase !== 'error' && (
        <div className="capture-overlay__pulse" aria-hidden />
      )}
    </div>
  )
}

export function toPhaseOverlay(phase: CapturePhase | string, label?: string): CaptureOverlayState {
  return {
    mode: 'phase',
    phase: phase as CapturePhase,
    label: phaseLabel(phase, label),
  }
}
