import { useCallback, useEffect, useRef, useState } from 'react'
import {
  capturePrint,
  fetchRecentPrints,
  pingRemote,
  reprintLast,
  reprintPhoto,
  stopLiveView,
} from '../api/client'
import { useDeviceStatus } from '../hooks/useDeviceStatus'
import { useReprintLastGesture } from '../hooks/useReprintLastGesture'
import type { CaptureResult, CaptureSource, DotKind, RecentPrint } from '../types'

function dotClass(kind: DotKind) {
  return `sys-dot is-${kind}`
}

function deviceDot(ok: boolean): DotKind {
  return ok ? 'ok' : 'warn'
}

const REMOTE_CLIENT_KEY = 'bkfire.remoteClientId'
const REMOTE_RECENT_LIMIT = 3

function remoteClientId(): string {
  try {
    let id = sessionStorage.getItem(REMOTE_CLIENT_KEY)
    if (!id) {
      id = crypto.randomUUID()
      sessionStorage.setItem(REMOTE_CLIENT_KEY, id)
    }
    return id
  } catch {
    return 'remote'
  }
}

export function RemotePage() {
  const [busy, setBusy] = useState(false)
  const [reprintOpen, setReprintOpen] = useState(false)
  const [copies, setCopies] = useState(1)
  const [toast, setToast] = useState<{ text: string; kind?: 'busy' | 'ok' | 'err' } | null>(null)
  const [recent, setRecent] = useState<RecentPrint[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [historyBust, setHistoryBust] = useState(0)
  const clientIdRef = useRef(remoteClientId())

  const { gphoto, webcam, printer, cloudinary, remote, lastPrint, setLastPrint, refresh } =
    useDeviceStatus(busy)

  const remoteOk = !!remote.connected

  useEffect(() => {
    const beat = () => void pingRemote(clientIdRef.current)
    beat()
    const id = window.setInterval(beat, 8000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    document.body.classList.toggle('is-reprint-open', reprintOpen)
    if (reprintOpen) {
      window.scrollTo(0, 0)
    }
    return () => document.body.classList.remove('is-reprint-open')
  }, [reprintOpen])

  const camOk = !!gphoto.connected
  const webOk = !!webcam.connected
  const captureSource: CaptureSource | null = camOk ? 'gphoto' : webOk ? 'webcam' : null
  const captureLabel = camOk ? 'Camera' : webOk ? 'Webcam' : 'Unavailable'

  const refreshRecent = useCallback(async () => {
    try {
      const items = await fetchRecentPrints(REMOTE_RECENT_LIMIT)
      setRecent(items)
      setSelectedIds((prev) => prev.filter((id) => items.some((item) => item.photo_id === id)))
    } catch {
      /* ignore poll errors */
    }
  }, [])

  useEffect(() => {
    void refreshRecent()
  }, [refreshRecent])

  useEffect(() => {
    if (!toast || toast.kind === 'busy') return
    const id = window.setTimeout(() => setToast(null), 5000)
    return () => window.clearTimeout(id)
  }, [toast])

  function showStatus(text: string, kind?: 'busy' | 'ok' | 'err') {
    setToast({ text, kind })
  }

  function rememberResult(data: CaptureResult) {
    setHistoryBust(Date.now())
    setLastPrint({
      photo_id: data.photo_id,
      layout_url: data.layout_url,
      photo_url: data.photo_url,
      captured_at: data.captured_at,
    })
    void refreshRecent()
  }

  function toggleSelect(photoId: string) {
    setSelectedIds((prev) =>
      prev.includes(photoId) ? prev.filter((id) => id !== photoId) : [...prev, photoId],
    )
  }

  async function runCapture() {
    if (!captureSource || busy) return
    setBusy(true)
    showStatus('Capturing → print…', 'busy')
    try {
      await stopLiveView()
      const data = await capturePrint(captureSource, 'floyd')
      showStatus(data.message || 'Done', data.printed ? 'ok' : 'err')
      rememberResult(data)
      setSelectedIds([data.photo_id])
    } catch (err) {
      showStatus(String(err instanceof Error ? err.message : err), 'err')
    } finally {
      setBusy(false)
      void refresh()
    }
  }

  async function runReprintSelected() {
    if (!selectedIds.length) {
      showStatus('Select at least 1 photo to reprint', 'err')
      return
    }
    const n = Math.max(1, Math.min(20, copies || 1))
    setCopies(n)
    setBusy(true)
    showStatus(
      selectedIds.length > 1
        ? `Reprinting ${selectedIds.length} × ${n}…`
        : n > 1
          ? `Reprinting ${n} copies…`
          : 'Reprinting…',
      'busy',
    )
    try {
      let last: CaptureResult | null = null
      for (const photoId of selectedIds) {
        last = await reprintPhoto(photoId, 'floyd', n)
      }
      showStatus(last?.message || 'Done', last?.printed ? 'ok' : 'err')
      if (last) rememberResult(last)
    } catch (err) {
      showStatus(String(err instanceof Error ? err.message : err), 'err')
    } finally {
      setBusy(false)
      void refresh()
    }
  }

  async function runReprintLast() {
    if (!lastPrint?.photo_id) {
      showStatus('No previous print to reprint', 'err')
      return
    }
    if (busy) return
    setBusy(true)
    showStatus('Reprinting last…', 'busy')
    try {
      const data = await reprintLast('floyd', 1)
      showStatus(data.message || 'Done', data.printed ? 'ok' : 'err')
      rememberResult(data)
    } catch (err) {
      showStatus(String(err instanceof Error ? err.message : err), 'err')
    } finally {
      setBusy(false)
      void refresh()
    }
  }

  const reprintLastDisabled = busy || !lastPrint?.photo_id || reprintOpen
  const {
    holding: reprintHolding,
    progress: reprintHoldProgress,
    onPointerDown: onReprintLastDown,
    onPointerUp: onReprintLastUp,
    onPointerCancel: onReprintLastCancel,
  } = useReprintLastGesture({
    disabled: reprintLastDisabled,
    onShortPress: () => void runReprintLast(),
    onLongPressComplete: () => setReprintOpen(true),
  })

  const bust = historyBust ? `?t=${historyBust}` : ''

  return (
    <div className={`remote-app${reprintOpen ? ' is-reprint-open' : ''}`}>
      <header className="brand-header remote-brand">
        <img
          className="brand-header__logo"
          src="/img/uts/lockup-full.png"
          alt="UTS and Ho Chi Minh City University of Technology"
        />
        <p className="remote-brand__tag">Remote control</p>
      </header>

      <div className="sysbar" aria-label="System status">
        <div className="sysbar__inner">
          <div className="sysbar__items">
            <div className="sys-item">
              <span className={dotClass(deviceDot(camOk))} />
              <span className="sys-label">Camera:</span>
              <span className={`sys-value${camOk ? '' : ' is-warn'}`}>
                {camOk ? gphoto.model || 'OK' : 'waiting'}
              </span>
            </div>
            <div className="sys-item">
              <span className="sys-sep">·</span>
              <span className={dotClass(deviceDot(webOk))} />
              <span className="sys-label">Webcam:</span>
              <span className={`sys-value${webOk ? '' : ' is-warn'}`}>
                {webOk ? webcam.model || 'OK' : 'not ready'}
              </span>
            </div>
            <div className="sys-item">
              <span className="sys-sep">·</span>
              <span className={dotClass(deviceDot(!!printer.connected))} />
              <span className="sys-label">Printer:</span>
              <span className={`sys-value${printer.connected ? '' : ' is-warn'}`}>
                {printer.connected ? `OK (${printer.backend || 'usb'})` : 'not found'}
              </span>
            </div>
            <div className="sys-item">
              <span className="sys-sep">·</span>
              <span className={dotClass(deviceDot(!!cloudinary.enabled))} />
              <span className="sys-label">Cloudinary:</span>
              <span className={`sys-value${cloudinary.enabled ? '' : ' is-warn'}`}>
                {cloudinary.enabled ? 'OK' : 'not configured'}
              </span>
            </div>
            <div className="sys-item">
              <span className="sys-sep">·</span>
              <span className={dotClass(deviceDot(remoteOk))} />
              <span className="sys-label">Remote:</span>
              <span className={`sys-value${remoteOk ? '' : ' is-warn'}`}>
                {remoteOk ? 'connected' : 'unconnected'}
              </span>
            </div>
            <div className="sys-item">
              <span className="sys-sep">·</span>
              <span className={dotClass(lastPrint?.photo_id ? 'ok' : 'muted')} />
              <span className="sys-label">Last:</span>
              <span className="sys-value">
                {lastPrint?.photo_id ? `#${lastPrint.photo_id}` : '—'}
              </span>
            </div>
          </div>
        </div>
      </div>

      <main className="remote-main">
        <button
          type="button"
          className="remote-capture"
          disabled={busy || !captureSource}
          onClick={() => void runCapture()}
        >
          <img src="/img/icons/icon-camera.svg" alt="" width={28} height={28} />
          <span className="remote-capture__label">
            {busy ? 'Working…' : `Capture · ${captureLabel}`}
          </span>
          {!captureSource && (
            <span className="remote-capture__hint">Camera and webcam offline</span>
          )}
        </button>

        <div className="remote-reprint-wrap">
          {!reprintOpen && (
            <button
              type="button"
              className={`remote-reprint-last${reprintHolding ? ' is-holding' : ''}${
                reprintHolding && reprintHoldProgress > 0.55 ? ' is-holding-intense' : ''
              }`}
              disabled={reprintLastDisabled}
              onPointerDown={onReprintLastDown}
              onPointerUp={onReprintLastUp}
              onPointerCancel={onReprintLastCancel}
              onPointerLeave={onReprintLastCancel}
              onContextMenu={(e) => e.preventDefault()}
            >
              <span
                className="remote-reprint-last__progress"
                style={{ width: `${reprintHoldProgress * 100}%` }}
                aria-hidden
              />
              <span className="remote-reprint-last__label">Reprint last</span>
              {lastPrint?.photo_id && (
                <span className="remote-reprint-last__id">#{lastPrint.photo_id.slice(0, 8)}</span>
              )}
            </button>
          )}

          {reprintOpen && (
            <section className="remote-reprint is-revealed" aria-label="Reprint">
              <div className="remote-reprint__head">
                <h2>Select photos</h2>
                <button
                  type="button"
                  className="remote-reprint__close"
                  disabled={busy}
                  onClick={() => setReprintOpen(false)}
                >
                  Close
                </button>
              </div>
              <p className="remote-reprint__hint">
                Tap photos to select, then reprint
                <span className="remote-reprint__meta">
                  {selectedIds.length}/{REMOTE_RECENT_LIMIT} selected
                </span>
              </p>

              <div className="remote-reprint__grid">
                {recent.length === 0 && (
                  <p className="remote-reprint__empty">No prints yet</p>
                )}
                {recent.map((item) => {
                  const selected = selectedIds.includes(item.photo_id)
                  return (
                    <button
                      key={item.photo_id}
                      type="button"
                      className={`remote-reprint__card${selected ? ' is-selected' : ''}`}
                      aria-pressed={selected}
                      disabled={busy}
                      onClick={() => toggleSelect(item.photo_id)}
                    >
                      <img
                        src={`${item.layout_color_url}${bust}`}
                        alt={`Layout ${item.photo_id}`}
                      />
                      <span className="remote-reprint__id">#{item.photo_id.slice(0, 8)}</span>
                    </button>
                  )
                })}
              </div>

              <div className="remote-reprint__actions">
                <label className="remote-copies" htmlFor="remoteCopies">
                  <span>Copies</span>
                  <input
                    id="remoteCopies"
                    type="number"
                    min={1}
                    max={20}
                    value={copies}
                    inputMode="numeric"
                    disabled={busy}
                    onChange={(e) => setCopies(Number.parseInt(e.target.value || '1', 10) || 1)}
                  />
                </label>
                <button
                  type="button"
                  className="remote-reprint__btn"
                  disabled={busy || selectedIds.length === 0}
                  onClick={() => void runReprintSelected()}
                >
                  Reprint selected
                </button>
              </div>
            </section>
          )}
        </div>
      </main>

      <div
        className={`toast remote-toast${toast?.kind ? ` is-${toast.kind}` : ''}`}
        role="status"
        aria-live="polite"
        hidden={!toast}
      >
        {toast?.text}
      </div>
    </div>
  )
}
