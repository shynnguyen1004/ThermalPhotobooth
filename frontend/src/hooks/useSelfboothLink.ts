import { useCallback, useEffect, useState } from 'react'
import { fetchSelfboothInfo } from '../api/client'
import type { SelfboothInfo } from '../types'

const POLL_MS = 20_000

export function useSelfboothLink() {
  const [info, setInfo] = useState<SelfboothInfo | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const data = await fetchSelfboothInfo()
      setInfo(data)
      setError(data.remote_url ? null : 'No LAN IP — connect WiFi')
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err))
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => void refresh(), POLL_MS)
    const onFocus = () => void refresh()
    window.addEventListener('focus', onFocus)
    return () => {
      window.clearInterval(id)
      window.removeEventListener('focus', onFocus)
    }
  }, [refresh])

  const qrSrc =
    info?.remote_url != null
      ? `/api/selfbooth/qr.png?port=${info.port}${info.lan_ip ? `&v=${encodeURIComponent(info.lan_ip)}` : ''}`
      : null

  return { info, qrSrc, error, refresh }
}
