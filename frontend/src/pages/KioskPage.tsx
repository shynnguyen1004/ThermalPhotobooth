import { useCallback, useEffect, useState } from 'react'
import { capturePrint, fetchRecentPrints, reprintPhoto } from '../api/client'
import { CaptureOverlay } from '../components/CaptureOverlay'
import { RemoteQrPanel } from '../components/RemoteQrPanel'
import { useTargetCursor } from '../context/TargetCursorContext'
import { useCaptureOverlay } from '../hooks/useCaptureOverlay'
import { useDeviceStatus } from '../hooks/useDeviceStatus'
import { useLivePreview } from '../hooks/useLivePreview'
import type { CaptureResult, CaptureSource, DitherStyle, DotKind, RecentPrint } from '../types'

function dotClass(kind: DotKind) {
  return `sys-dot is-${kind}`
}

function deviceDot(ok: boolean): DotKind {
  return ok ? 'ok' : 'warn'
}

export function KioskPage() {
  const [busy, setBusy] = useState(false)
  const [ditherStyle, setDitherStyle] = useState<DitherStyle>('floyd')
  const [copies, setCopies] = useState(1)
  const [autoPrint, setAutoPrint] = useState(() => {
    try {
      const stored = localStorage.getItem('photobooth-auto-print')
      if (stored === null) return true
      return stored === 'true'
    } catch {
      return true
    }
  })
  const [toast, setToast] = useState<{ text: string; kind?: 'busy' | 'ok' | 'err' } | null>(null)
  const [recent, setRecent] = useState<RecentPrint[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [historyBust, setHistoryBust] = useState(0)
  const { enabled: targetCursorOn, toggle: toggleTargetCursor } = useTargetCursor()
  const {
    overlay,
    setOverlay,
    startPolling,
    stopPolling,
    showPhase,
    clearOverlay,
  } = useCaptureOverlay()

  const { gphoto, webcam, printer, cloudinary, remote, lastPrint, setLastPrint, refresh } =
    useDeviceStatus(busy)
  const camOk = !!gphoto.connected
  const webOk = !!webcam.connected
  const remoteOk = !!remote.connected
  const {
    videoRef,
    previewWanted,
    isLive,
    isSonyLive,
    sonyStreamUrl,
    onSonyStreamError,
    subtitle,
    setSubtitle,
    resBadge,
    setWanted,
    updateResBadge,
    withPreviewPaused,
    resumePreview,
    stopLivePreviewAsync,
    cameras,
    selectedDeviceId,
    selectCamera,
  } = useLivePreview(busy, camOk)

  const refreshRecent = useCallback(async () => {
    try {
      const items = await fetchRecentPrints(6)
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
    const id = window.setTimeout(() => setToast(null), 6000)
    return () => window.clearTimeout(id)
  }, [toast])

  useEffect(() => {
    try {
      localStorage.setItem('photobooth-auto-print', String(autoPrint))
    } catch {
      /* ignore */
    }
  }, [autoPrint])

  function showStatus(text: string, kind?: 'busy' | 'ok' | 'err') {
    setToast({ text, kind })
    if (!isLive && kind !== 'ok') setSubtitle(text)
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

  async function runCapture(source: CaptureSource) {
    const n = Math.max(1, Math.min(20, copies || 1))
    setCopies(n)
    setBusy(true)
    showStatus(autoPrint ? 'Capturing…' : 'Capturing (save only)…', 'busy')
    try {
      // 1) Release live view + fire shutter ASAP (do not wait for countdown).
      await stopLivePreviewAsync()
      await new Promise((r) =>
        window.setTimeout(r, source === 'gphoto' ? 350 : 250),
      )

      const capturePromise = withPreviewPaused(
        () => capturePrint(source, ditherStyle, { copies: n, autoPrint }),
        { resume: false, alreadyStopped: true },
      )

      // 2) Countdown starts only after the capture request is already in flight.
      for (const count of [3, 2, 1] as const) {
        setOverlay({ mode: 'countdown', count })
        await new Promise((r) => window.setTimeout(r, 1000))
      }

      // 3) After 3-2-1, follow backend phases (Processing → … → Printing).
      showPhase('capturing', 'Capturing…')
      startPolling()
      const data = await capturePromise
      stopPolling()
      const ok = !!(data.printed || !autoPrint)
      showPhase('done', ok ? (data.printed ? 'Done' : 'Saved') : 'Finished')
      showStatus(data.message || 'Done', ok ? 'ok' : 'err')
      rememberResult(data)
      setSelectedIds([data.photo_id])
      await new Promise((r) => window.setTimeout(r, 2000))
      clearOverlay()
      await resumePreview()
    } catch (err) {
      stopPolling()
      const msg = String(err instanceof Error ? err.message : err)
      showPhase('error', 'Capture failed')
      showStatus(msg, 'err')
      await new Promise((r) => window.setTimeout(r, 2000))
      clearOverlay()
      await resumePreview()
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
    showPhase('processing', 'Processing…')
    startPolling()
    showStatus(
      selectedIds.length > 1
        ? `Reprinting ${selectedIds.length} photos × ${n} copies…`
        : n > 1
          ? `Reprinting ${n} copies…`
          : 'Reprinting…',
      'busy',
    )
    try {
      let last: CaptureResult | null = null
      for (const photoId of selectedIds) {
        last = await reprintPhoto(photoId, ditherStyle, n)
      }
      stopPolling()
      showPhase('done', 'Done')
      showStatus(last?.message || 'Done', last?.printed ? 'ok' : 'err')
      if (last) rememberResult(last)
      await new Promise((r) => window.setTimeout(r, 2000))
      clearOverlay()
    } catch (err) {
      stopPolling()
      showPhase('error', 'Reprint failed')
      showStatus(String(err instanceof Error ? err.message : err), 'err')
      await new Promise((r) => window.setTimeout(r, 2000))
      clearOverlay()
    } finally {
      setBusy(false)
      void refresh()
    }
  }

  const bust = historyBust ? `?t=${historyBust}` : ''

  return (
    <div className="app">
      <header className="brand-header">
        <img
          className="brand-header__logo"
          src="/img/uts/lockup-full.png"
          alt="UTS and Ho Chi Minh City University of Technology"
        />
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

      <main className="stage">
        <aside className="stage-panel stage-panel--left control-panel" aria-label="Capture controls">
          <fieldset className="style-chip style-chip--rail" aria-label="Print dither style">
            <legend>Print style</legend>
            <label className="style-chip__opt">
              <input
                type="radio"
                name="ditherStyle"
                value="floyd"
                checked={ditherStyle === 'floyd'}
                onChange={() => setDitherStyle('floyd')}
              />
              <span>Floyd</span>
            </label>
            <label className="style-chip__opt">
              <input
                type="radio"
                name="ditherStyle"
                value="comic"
                checked={ditherStyle === 'comic'}
                onChange={() => setDitherStyle('comic')}
              />
              <span>Comic-dot</span>
            </label>
          </fieldset>

          <label className="copies-chip copies-chip--rail" htmlFor="captureCopies">
            <span>Copies</span>
            <input
              id="captureCopies"
              type="number"
              min={1}
              max={20}
              value={copies}
              inputMode="numeric"
              aria-label="Print copies"
              disabled={busy || !autoPrint}
              onChange={(e) => setCopies(Number.parseInt(e.target.value || '1', 10) || 1)}
            />
          </label>

          <button
            type="button"
            className="print-toggle"
            aria-pressed={autoPrint}
            disabled={busy}
            title="Toggle automatic printing after capture"
            onClick={() => setAutoPrint((on) => !on)}
          >
            Auto print <span>{autoPrint ? 'ON' : 'OFF'}</span>
          </button>

          <div className="control-panel__bottom">
          <RemoteQrPanel />

          <div className="actions actions--rail" role="group" aria-label="Capture and print">
            <button
              className="btn btn--primary btn--rail"
              type="button"
              disabled={busy || !camOk}
              onClick={() => void runCapture('gphoto')}
            >
              <img src="/img/icons/icon-camera.svg" alt="" width={22} height={22} />
              <span className="btn__text">
                <span className="btn__label">Camera</span>
              </span>
            </button>

            <button
              className="btn btn--primary btn--solid btn--rail"
              type="button"
              disabled={busy || !webOk}
              onClick={() => void runCapture('webcam')}
            >
              <img src="/img/icons/icon-webcam.svg" alt="" width={22} height={22} />
              <span className="btn__text">
                <span className="btn__label">Webcam</span>
              </span>
            </button>
          </div>

          <p className="control-panel__credit">
            Developed by{' '}
            <a
              href="https://shynnguyen.vercel.app"
              target="_blank"
              rel="noopener noreferrer"
            >
              @shyn._.nguyen
            </a>
            <br />
            Made for TNE Commencement Day 2026
          </p>
          </div>
        </aside>

        <div className="stage-center">
          <section
            className={`viewport${isLive ? ' is-live' : ''}${busy ? ' is-busy' : ''}`}
            aria-label="Live camera feed"
          >
            <video
              ref={videoRef}
              className="viewport__video"
              playsInline
              muted
              autoPlay
              hidden={!isLive || isSonyLive}
              onLoadedMetadata={updateResBadge}
            />
            {isSonyLive && sonyStreamUrl && (
              <img
                className="viewport__video viewport__liveview"
                src={sonyStreamUrl}
                alt="Sony live view"
                onError={onSonyStreamError}
              />
            )}

            <div className="viewport__idle" hidden={isLive}>
              <div className="viewport__focus">
                <img
                  className="viewport__cam-icon"
                  src="/img/icons/icon-camera-placeholder.svg"
                  alt=""
                  width={80}
                  height={80}
                />
                <img
                  className="viewport__bracket"
                  src="/img/icons/icon-focus-bracket.svg"
                  alt=""
                  width={72}
                  height={72}
                />
              </div>
              <p className="viewport__title">Live camera</p>
              <p className="viewport__subtitle">{subtitle}</p>
              {!isLive && (
                <button type="button" className="enable-cam" onClick={() => void setWanted(true, true)}>
                  {previewWanted ? 'Allow Camera' : 'Enable Webcam Preview'}
                </button>
              )}
            </div>

            <div className={`live-badge${isLive ? '' : ' is-off'}`}>
              <span className="live-badge__dot" />
              <span>{isLive ? 'LIVE' : 'OFF'}</span>
            </div>
            <button
              type="button"
              className="preview-toggle"
              aria-pressed={previewWanted}
              title="Toggle live webcam"
              onClick={() => void setWanted(!previewWanted, true)}
            >
              Preview <span>{previewWanted ? 'ON' : 'OFF'}</span>
            </button>
            {cameras.length > 0 && (
              <label className="camera-picker" title="Select preview camera">
                <span className="camera-picker__label">Cam</span>
                <select
                  className="camera-picker__select"
                  value={selectedDeviceId}
                  disabled={busy}
                  aria-label="Select preview camera"
                  onChange={(e) => void selectCamera(e.target.value)}
                >
                  {!selectedDeviceId && <option value="">Default</option>}
                  {cameras.map((cam) => (
                    <option key={cam.deviceId} value={cam.deviceId}>
                      {cam.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="res-badge">{resBadge}</div>
            <CaptureOverlay state={overlay} />
          </section>
        </div>

        <aside className="stage-panel stage-panel--right history-panel" aria-label="Recent prints">
          <div className="history-panel__head">
            <h2>Recent prints</h2>
            <div className="history-panel__head-actions">
              <span className="history-panel__meta">{selectedIds.length}/6 selected</span>
              <button
                type="button"
                className="cursor-toggle"
                aria-pressed={targetCursorOn}
                title="Toggle custom cursor effect"
                onClick={toggleTargetCursor}
              >
                Cursor <span>{targetCursorOn ? 'ON' : 'OFF'}</span>
              </button>
            </div>
          </div>
          <p className="history-panel__hint">Color layouts (Cloudinary) — last 6 prints</p>

          <div className="history-panel__grid">
            {recent.length === 0 && (
              <p className="history-panel__empty">No prints yet — capture a photo to see it here</p>
            )}
            {recent.map((item) => {
              const selected = selectedIds.includes(item.photo_id)
              return (
                <button
                  key={item.photo_id}
                  type="button"
                  className={`history-card${selected ? ' is-selected' : ''}`}
                  aria-pressed={selected}
                  disabled={busy}
                  onClick={() => toggleSelect(item.photo_id)}
                >
                  <img
                    src={`${item.layout_color_url}${bust}`}
                    alt={`Layout ${item.photo_id}`}
                  />
                  <span className="history-card__id">#{item.photo_id.slice(0, 8)}</span>
                  {item.captured_at && (
                    <span className="history-card__time">{item.captured_at}</span>
                  )}
                </button>
              )
            })}
          </div>

          <div className="history-panel__actions">
            <label className="copies-chip copies-chip--panel" htmlFor="reprintCopies">
              <span>Copies</span>
              <input
                id="reprintCopies"
                type="number"
                min={1}
                max={20}
                value={copies}
                inputMode="numeric"
                aria-label="Reprint copies"
                disabled={busy}
                onChange={(e) => setCopies(Number.parseInt(e.target.value || '1', 10) || 1)}
              />
            </label>
            <button
              className="btn btn--outline btn--panel"
              type="button"
              disabled={busy || selectedIds.length === 0}
              onClick={() => void runReprintSelected()}
            >
              <img src="/img/icons/icon-reprint.svg" alt="" width={20} height={20} />
              <span className="btn__text">
                <span className="btn__label">Reprint selected</span>
                <span className="btn__hint">
                  {selectedIds.length
                    ? `${selectedIds.length} photos × ${copies}`
                    : 'Select photos above'}
                </span>
              </span>
            </button>
          </div>
        </aside>

        <div
          className={`toast${toast?.kind ? ` is-${toast.kind}` : ''}`}
          role="status"
          aria-live="polite"
          hidden={!toast}
        >
          {toast?.text}
        </div>
      </main>
    </div>
  )
}
