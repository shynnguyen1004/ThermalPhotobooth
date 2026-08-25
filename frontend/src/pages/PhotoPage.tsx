import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchConfig, fetchPhotoAssets } from '../api/client'
import type { GuestPhotoAssets } from '../types'

export function PhotoPage() {
  const { photoId = '' } = useParams()
  const [orgName, setOrgName] = useState('University of Technology Sydney')
  const [assets, setAssets] = useState<GuestPhotoAssets | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    document.title = `Your photo — ${orgName}`
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
        setError(err instanceof Error ? err.message : 'Could not load photo')
      })
  }, [photoId])

  const photoUrl = assets?.photo_url ?? `/photos/${photoId}.jpg`
  const layoutUrl = assets?.layout_url ?? `/prints/${photoId}_layout.png`

  return (
    <main className="guest-card">
      <img
        className="guest-lockup"
        src="/img/uts/lockup-full.png"
        alt="UTS and HCMUT"
      />
      <span className="event-pill">Photobooth</span>
      <h1>Your photo</h1>
      <p className="muted">ID: {photoId}</p>

      {error && <p className="guest-error">{error}</p>}

      {!error && (
        <>
          <section className="guest-section">
            <h2 className="guest-section__title">Color photo</h2>
            <img className="guest-photo" src={photoUrl} alt="Color photobooth photo" />
            <a className="cta cta--compact" href={photoUrl} download={`uts-${photoId}.jpg`}>
              Download color photo
            </a>
          </section>

          {assets?.layout_url !== null && (
            <section className="guest-section">
              <h2 className="guest-section__title">Print layout</h2>
              <img className="guest-layout" src={layoutUrl} alt="Layout photobooth" />
              <a
                className="cta cta--compact cta--outline"
                href={layoutUrl}
                download={`uts-${photoId}-layout.png`}
              >
                Download print layout
              </a>
            </section>
          )}
        </>
      )}
    </main>
  )
}
