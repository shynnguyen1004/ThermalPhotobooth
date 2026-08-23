import { useEffect, useMemo, useState } from 'react'
import { capturePrint, reprintLast } from '../api/client'
import { useClock } from '../hooks/useClock'
import { useDeviceStatus } from '../hooks/useDeviceStatus'
import { useLivePreview } from '../hooks/useLivePreview'
import type { CaptureResult, CaptureSource, DitherStyle, DotKind } from '../types'

function dotClass(kind: DotKind) {
  return `sys-dot is-${kind}`
}

function deviceDot(ok: boolean): DotKind {
  return ok ? 'ok' : 'warn'
}

export function KioskPage() {
  const { time, date } = useClock()
  const [busy, setBusy] = useState(false)
  const [ditherStyle, setDitherStyle] = useState<DitherStyle>('floyd')
  const [copies, setCopies] = useState(1)
  const [toast, setToast] = useState<{ text: string; kind?: 'busy' | 'ok' | 'err' } | null>(null)
  const [result, setResult] = useState<CaptureResult | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [resultBust, setResultBust] = useState(0)

  const { gphoto, webcam, printer, cloudinary, lastPrint, setLastPrint, refresh } =
    useDeviceStatus(busy)
  const {
    videoRef,
    previewWanted,
    isLive,
    subtitle,
    setSubtitle,
    resBadge,
    setWanted,
    updateResBadge,
    withPreviewPaused,
  } = useLivePreview(busy)

  const camOk = !!gphoto.connected
  const webOk = !!webcam.connected
  const hasLast = !!(lastPrint?.photo_id || result?.photo_id)

  const hints = useMemo(
    () => ({
      camera: camOk ? 'Capture by Camera & Print' : gphoto.error || 'Camera disconnected',
      webcam: webOk ? 'Capture by Webcam & Print' : webcam.error || 'Webcam unavailable',
      reprint: hasLast ? 'Reprint' : 'No previous print',
    }),
    [camOk, webOk, hasLast, gphoto.error, webcam.error],
  )

  useEffect(() => {
    if (!toast || toast.kind === 'busy') return
    const id = window.setTimeout(() => setToast(null), 6000)
    return () => window.clearTimeout(id)
  }, [toast])

  function showStatus(text: string, kind?: 'busy' | 'ok' | 'err') {
    setToast({ text, kind })
    if (!isLive && kind !== 'ok') setSubtitle(text)
  }

  function showResult(data: CaptureResult) {
    setResult(data)
    setResultBust(Date.now())
    setDrawerOpen(true)
    setLastPrint({
      photo_id: data.photo_id,
      layout_url: data.layout_url,
      photo_url: data.photo_url,
      captured_at: data.captured_at,
    })
  }

  async function runCapture(source: CaptureSource, busyLabel: string) {
    setBusy(true)
    showStatus(busyLabel, 'busy')
    const doRequest = () => capturePrint(source, ditherStyle)
    try {
      const data =
        source === 'webcam' ? await withPreviewPaused(doRequest) : await doRequest()
      showStatus(data.message || 'Xong', data.printed ? 'ok' : 'err')
      showResult(data)
    } catch (err) {
      showStatus(String(err instanceof Error ? err.message : err), 'err')
    } finally {
      setBusy(false)
      void refresh()
    }
  }

  async function runReprint() {
    const n = Math.max(1, Math.min(20, copies || 1))
    setCopies(n)
    setBusy(true)
    showStatus(n > 1 ? `Đang in lại ${n} bản…` : 'Đang in lại lần gần nhất…', 'busy')
    try {
      const data = await reprintLast(ditherStyle, n)
      showStatus(data.message || 'Xong', data.printed ? 'ok' : 'err')
      showResult(data)
    } catch (err) {
      showStatus(String(err instanceof Error ? err.message : err), 'err')
    } finally {
      setBusy(false)
      void refresh()
    }
  }

  const bust = resultBust ? `?t=${resultBust}` : ''

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__logos">
          <img
            className="topbar__logo topbar__logo--uni"
            src="/img/logo-bachkhoa.png"
            alt="ĐH Bách Khoa TP.HCM"
            width={44}
            height={44}
          />
          <span className="topbar__divider" aria-hidden="true" />
          <img
            className="topbar__logo topbar__logo--club"
            src="/img/logo-bkfire.png"
            alt="BK FIRE"
            width={40}
            height={40}
          />
        </div>

        <div className="topbar__center">
          <span className="event-pill">📸 Photobooth · Club Day 2026</span>
        </div>

        <div className="topbar__clock" aria-live="polite">
          <time className="topbar__time">{time}</time>
          <time className="topbar__date">{date}</time>
        </div>
      </header>

      <div className="sysbar" aria-label="Trạng thái hệ thống">
        <div className="sysbar__inner">
          <div className="sysbar__items">
            <div className="sys-item">
              <span className={dotClass(deviceDot(camOk))} />
              <span className="sys-label">Máy ảnh:</span>
              <span className={`sys-value${camOk ? '' : ' is-warn'}`}>
                {camOk ? gphoto.model || 'OK' : 'chờ kết nối'}
              </span>
            </div>
            <div className="sys-item">
              <span className="sys-sep">·</span>
              <span className={dotClass(deviceDot(webOk))} />
              <span className="sys-label">Webcam:</span>
              <span className={`sys-value${webOk ? '' : ' is-warn'}`}>
                {webOk ? webcam.model || 'OK' : 'chưa sẵn sàng'}
              </span>
            </div>
            <div className="sys-item">
              <span className="sys-sep">·</span>
              <span className={dotClass(deviceDot(!!printer.connected))} />
              <span className="sys-label">Printer:</span>
              <span className={`sys-value${printer.connected ? '' : ' is-warn'}`}>
                {printer.connected ? `OK (${printer.backend || 'usb'})` : 'chưa thấy'}
              </span>
            </div>
            <div className="sys-item">
              <span className="sys-sep">·</span>
              <span className={dotClass(deviceDot(!!cloudinary.enabled))} />
              <span className="sys-label">Cloudinary:</span>
              <span className={`sys-value${cloudinary.enabled ? '' : ' is-warn'}`}>
                {cloudinary.enabled ? 'OK' : 'chưa cấu hình'}
              </span>
            </div>
            <div className="sys-item">
              <span className="sys-sep">·</span>
              <span className={dotClass(hasLast ? 'ok' : 'muted')} />
              <span className="sys-label">Last:</span>
              <span className="sys-value">
                {lastPrint?.photo_id ? `#${lastPrint.photo_id}` : '—'}
              </span>
            </div>
          </div>
          <div className="sysbar__pulse" title="System">
            <span className="sys-label">SYS</span>
            <span className="pulse-bars" aria-hidden="true">
              <i /><i /><i /><i /><i /><i /><i />
            </span>
          </div>
        </div>
      </div>

      <main className="stage">
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
            hidden={!isLive}
            onLoadedMetadata={updateResBadge}
          />

          <div className="viewport__idle">
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
            <p className="viewport__title">LIVE CAMERA FEED</p>
            <p className="viewport__subtitle">{subtitle}</p>
            {!isLive && (
              <button type="button" className="enable-cam" onClick={() => void setWanted(true, true)}>
                {previewWanted ? 'Cho phép Camera' : 'Bật Preview Webcam'}
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
            title="Bật/tắt live webcam"
            onClick={() => void setWanted(!previewWanted, true)}
          >
            Preview <span>{previewWanted ? 'ON' : 'OFF'}</span>
          </button>
          <div className="res-badge">{resBadge}</div>

          <fieldset className="style-chip" aria-label="Kiểu dither in">
            <legend>Kiểu in</legend>
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
        </section>

        <aside className="result-drawer" hidden={!drawerOpen} aria-label="Kết quả chụp">
          <div className="result-drawer__head">
            <h2>Kết quả</h2>
            <button
              type="button"
              className="result-drawer__close"
              aria-label="Đóng"
              onClick={() => setDrawerOpen(false)}
            >
              ×
            </button>
          </div>
          <p className="result-drawer__msg">
            {result
              ? `#${result.photo_id} · ${result.captured_at || ''} · QR: ${
                  result.cloudinary_url || result.qr_url || ''
                }`
              : ''}
          </p>
          {result && (
            <>
              <img
                className="result-drawer__photo"
                src={`${result.photo_url}${bust}`}
                alt="Ảnh đã chụp"
              />
              <div className="result-drawer__thumbs">
                {(result.frame_urls || []).map((url, i) => (
                  <figure key={url}>
                    <figcaption>Tấm {i + 1}</figcaption>
                    <img src={`${url}${bust}`} alt={`Frame ${i + 1}`} />
                  </figure>
                ))}
              </div>
              <figure className="result-drawer__print">
                <figcaption>Layout in (thermal)</figcaption>
                <img src={`${result.layout_url}${bust}`} alt="Layout máy in nhiệt" />
              </figure>
              {result.layout_color_url && (
                <figure className="result-drawer__print">
                  <figcaption>Layout màu (guest)</figcaption>
                  <img src={`${result.layout_color_url}${bust}`} alt="Layout màu cho guest" />
                </figure>
              )}
            </>
          )}
        </aside>

        <div className="actions" role="group" aria-label="Chụp và in">
          <button
            className="btn btn--primary"
            type="button"
            disabled={busy || !camOk}
            onClick={() => void runCapture('gphoto', 'Đang chụp bằng máy ảnh → Cloudinary → in…')}
          >
            <img src="/img/icons/icon-camera.svg" alt="" width={22} height={22} />
            <span className="btn__text">
              <span className="btn__label">Chụp bằng Máy Ảnh &amp; In</span>
              <span className="btn__hint">{hints.camera}</span>
            </span>
          </button>

          <button
            className="btn btn--primary btn--solid"
            type="button"
            disabled={busy || !webOk}
            onClick={() => void runCapture('webcam', 'Đang chụp bằng webcam → Cloudinary → in…')}
          >
            <img src="/img/icons/icon-webcam.svg" alt="" width={22} height={22} />
            <span className="btn__text">
              <span className="btn__label">Chụp bằng Webcam &amp; In</span>
              <span className="btn__hint">{hints.webcam}</span>
            </span>
          </button>

          <div className="reprint-group">
            <label className="copies-chip" htmlFor="reprintCopies">
              <span>Copies</span>
              <input
                id="reprintCopies"
                type="number"
                min={1}
                max={20}
                value={copies}
                inputMode="numeric"
                aria-label="Số bản in lại"
                onChange={(e) => setCopies(Number.parseInt(e.target.value || '1', 10) || 1)}
              />
            </label>
            <button
              className="btn btn--outline"
              type="button"
              disabled={busy || !hasLast}
              onClick={() => void runReprint()}
            >
              <img src="/img/icons/icon-reprint.svg" alt="" width={20} height={20} />
              <span className="btn__text">
                <span className="btn__label">In lại</span>
                <span className="btn__hint">{hints.reprint}</span>
              </span>
            </button>
          </div>
        </div>

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
