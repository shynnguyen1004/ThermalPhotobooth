import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchConfig, fetchPhotoAssets } from '../api/client'
import type { GuestPhotoAssets } from '../types'

export function PhotoPage() {
  const { photoId = '' } = useParams()
  const [orgName, setOrgName] = useState('BK FIRE')
  const [assets, setAssets] = useState<GuestPhotoAssets | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    document.title = `Ảnh của bạn — ${orgName}`
  }, [orgName])

  useEffect(() => {
    void fetchConfig().then((cfg) => setOrgName(cfg.org_name))
  }, [])

  useEffect(() => {
    if (!photoId) return
    setError('')
    setAssets(null)
    void fetchPhotoAssets(photoId)
      .then(setAssets)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Không tải được ảnh')
      })
  }, [photoId])

  const photoUrl = assets?.photo_url ?? `/photos/${photoId}.jpg`
  const layoutUrl = assets?.layout_url ?? `/prints/${photoId}_layout.png`

  return (
    <main className="guest-card">
      <div className="guest-logos">
        <img src="/img/logo-bachkhoa.png" alt="BK TP.HCM" width={48} height={48} />
        <img src="/img/logo-bkfire.png" alt="BK FIRE" width={48} height={48} />
      </div>
      <span className="event-pill">📸 Photobooth · Club Day 2026</span>
      <h1>Ảnh Club Day của bạn</h1>
      <p className="muted">Mã: {photoId}</p>

      {error && <p className="guest-error">{error}</p>}

      {!error && (
        <>
          <section className="guest-section">
            <h2 className="guest-section__title">Ảnh màu</h2>
            <img className="guest-photo" src={photoUrl} alt="Ảnh photobooth màu" />
            <a
              className="cta cta--compact"
              href={photoUrl}
              download={`bkfire-${photoId}.jpg`}
            >
              Tải ảnh màu
            </a>
          </section>

          {assets?.layout_url !== null && (
            <section className="guest-section">
              <h2 className="guest-section__title">Layout in</h2>
              <img className="guest-layout" src={layoutUrl} alt="Layout photobooth" />
              <a
                className="cta cta--compact cta--outline"
                href={layoutUrl}
                download={`bkfire-${photoId}-layout.png`}
              >
                Tải layout in
              </a>
            </section>
          )}
        </>
      )}
    </main>
  )
}
