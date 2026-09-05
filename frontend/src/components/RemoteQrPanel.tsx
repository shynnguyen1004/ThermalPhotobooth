import { useSelfboothLink } from '../hooks/useSelfboothLink'

export function RemoteQrPanel() {
  const { info, qrSrc, error } = useSelfboothLink()

  return (
    <div className="remote-qr-panel" aria-label="Remote control QR">
      <p className="remote-qr-panel__title">Phone remote</p>
      <p className="remote-qr-panel__hint">Scan to open /remote on the same WiFi</p>
      {qrSrc ? (
        <img
          className="remote-qr-panel__img"
          src={qrSrc}
          alt="QR code for remote photobooth control"
          width={160}
          height={160}
        />
      ) : (
        <div className="remote-qr-panel__placeholder" aria-hidden>
          QR unavailable
        </div>
      )}
      {info?.remote_url && (
        <p className="remote-qr-panel__url" title={info.remote_url}>
          {info.remote_url}
        </p>
      )}
      {error && <p className="remote-qr-panel__error">{error}</p>}
    </div>
  )
}
