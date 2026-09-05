import { useCallback, useEffect, useState } from 'react'
import { fetchStatus } from '../api/client'
import type { DeviceInfo, StatusResponse } from '../types'

const emptyDevice: DeviceInfo = { connected: false }

export function useDeviceStatus(busy: boolean) {
  const [status, setStatus] = useState<StatusResponse>({})
  const [lastPrint, setLastPrint] = useState<StatusResponse['last_print']>(null)

  const refresh = useCallback(async () => {
    try {
      const data = await fetchStatus()
      setStatus(data)
      if (data.last_print) setLastPrint(data.last_print)
    } catch {
      /* ignore poll errors */
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => {
      if (!busy) void refresh()
    }, 8000)
    return () => window.clearInterval(id)
  }, [busy, refresh])

  const gphoto = status.cameras?.gphoto || emptyDevice
  const webcam = status.cameras?.webcam || emptyDevice
  const printer = status.printer || emptyDevice
  const cloudinary = status.cloudinary || emptyDevice
  const remote = status.remote || emptyDevice

  return {
    gphoto,
    webcam,
    printer,
    cloudinary,
    remote,
    lastPrint,
    setLastPrint,
    refresh,
  }
}
