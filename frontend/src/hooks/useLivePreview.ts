import { useCallback, useEffect, useRef, useState } from 'react'
import { stopLiveView } from '../api/client'

const STORAGE_KEY = 'bkfire.previewCameraId'
export const SONY_LIVEVIEW_ID = '__sony_usb__'

export type CameraOption = {
  deviceId: string
  label: string
}

function cameraApiAvailable() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
}

export function explainCameraBlock() {
  if (!window.isSecureContext) {
    return 'Open via http://127.0.0.1:5173 or :8000 (localhost) to use the camera'
  }
  if (!cameraApiAvailable()) {
    return 'This browser cannot access the Camera API'
  }
  return 'Tap “Allow Camera” to show the permission prompt'
}

function loadStoredDeviceId(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

function saveStoredDeviceId(id: string) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

function labelFor(device: MediaDeviceInfo, index: number): string {
  const raw = (device.label || '').trim()
  if (raw) return raw
  return `Camera ${index + 1}`
}

export function useLivePreview(busy: boolean, sonyConnected = false) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const wantedRef = useRef(false)
  const startingRef = useRef(false)
  const deviceIdRef = useRef(loadStoredDeviceId())
  const liveviewBustRef = useRef(0)

  const [previewWanted, setPreviewWanted] = useState(false)
  const [isLive, setIsLive] = useState(false)
  const [isSonyLive, setIsSonyLive] = useState(false)
  const [sonyStreamUrl, setSonyStreamUrl] = useState('')
  const [subtitle, setSubtitle] = useState('Preview is off — tap to enable when needed')
  const [resBadge, setResBadge] = useState('—')
  const [cameras, setCameras] = useState<CameraOption[]>([])
  const [selectedDeviceId, setSelectedDeviceId] = useState(deviceIdRef.current)

  const updateResBadge = useCallback(() => {
    const video = videoRef.current
    if (!video?.videoWidth) {
      setResBadge('—')
      return
    }
    const long = Math.max(video.videoWidth, video.videoHeight)
    setResBadge(long >= 1800 ? '1080p' : long >= 1200 ? '720p' : `${video.videoWidth}×${video.videoHeight}`)
  }, [])

  const refreshCameras = useCallback(async () => {
    const list: CameraOption[] = []
    if (sonyConnected) {
      list.push({ deviceId: SONY_LIVEVIEW_ID, label: 'Sony USB (Live View)' })
    }

    if (cameraApiAvailable()) {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices()
        devices
          .filter((d) => d.kind === 'videoinput' && d.deviceId)
          .forEach((d, i) => list.push({ deviceId: d.deviceId, label: labelFor(d, i) }))
      } catch {
        /* ignore */
      }
    }

    setCameras(list)

    const current = deviceIdRef.current
    if (current === SONY_LIVEVIEW_ID && !sonyConnected) {
      deviceIdRef.current = ''
      setSelectedDeviceId('')
      saveStoredDeviceId('')
    } else if (current && current !== SONY_LIVEVIEW_ID && !list.some((c) => c.deviceId === current)) {
      deviceIdRef.current = ''
      setSelectedDeviceId('')
      saveStoredDeviceId('')
    } else if (!current && list.length === 1) {
      deviceIdRef.current = list[0].deviceId
      setSelectedDeviceId(list[0].deviceId)
      saveStoredDeviceId(list[0].deviceId)
    }
    return list
  }, [sonyConnected])

  const stopWebcamPreview = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
  }, [])

  const stopSonyPreview = useCallback(async () => {
    setSonyStreamUrl('')
    setIsSonyLive(false)
    try {
      await stopLiveView()
    } catch {
      /* ignore */
    }
  }, [])

  const stopLivePreview = useCallback(() => {
    stopWebcamPreview()
    void stopSonyPreview()
    setIsLive(false)
    setResBadge('—')
  }, [stopSonyPreview, stopWebcamPreview])

  const startSonyLiveView = useCallback(async () => {
    stopWebcamPreview()
    setSubtitle('Connecting Sony live view…')
    setResBadge('LV')
    // Bust cache so <img> reconnects to MJPEG stream
    liveviewBustRef.current += 1
    const url = `/api/liveview?t=${liveviewBustRef.current}`
    setSonyStreamUrl(url)
    setIsSonyLive(true)
    setIsLive(true)
    setSubtitle('Sony USB · Live View')
    return true
  }, [stopWebcamPreview])

  const startWebcamPreview = useCallback(
    async (fromUserGesture = false) => {
      if (!cameraApiAvailable()) {
        setSubtitle(explainCameraBlock())
        return false
      }
      await stopSonyPreview()
      if (streamRef.current) {
        stopWebcamPreview()
      }

      setSubtitle(fromUserGesture ? 'Requesting camera permission…' : 'Connecting webcam…')
      try {
        const deviceId = deviceIdRef.current
        const videoConstraint: MediaTrackConstraints = {
          width: { ideal: 1920 },
          height: { ideal: 1080 },
          ...(deviceId && deviceId !== SONY_LIVEVIEW_ID
            ? { deviceId: { exact: deviceId } }
            : { facingMode: 'user' }),
        }
        let stream: MediaStream
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: videoConstraint,
          })
        } catch (firstErr) {
          if (deviceId && deviceId !== SONY_LIVEVIEW_ID) {
            deviceIdRef.current = ''
            setSelectedDeviceId('')
            saveStoredDeviceId('')
            stream = await navigator.mediaDevices.getUserMedia({
              audio: false,
              video: {
                facingMode: 'user',
                width: { ideal: 1920 },
                height: { ideal: 1080 },
              },
            })
          } else {
            throw firstErr
          }
        }
        if (!wantedRef.current) {
          stream.getTracks().forEach((t) => t.stop())
          return false
        }
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play().catch(() => {})
        }

        const list = await refreshCameras()
        const trackId = stream.getVideoTracks()[0]?.getSettings().deviceId || ''
        if (trackId) {
          deviceIdRef.current = trackId
          setSelectedDeviceId(trackId)
          saveStoredDeviceId(trackId)
        }

        setIsSonyLive(false)
        setIsLive(true)
        updateResBadge()
        const name =
          list.find((c) => c.deviceId === (trackId || deviceIdRef.current))?.label ||
          'Live preview'
        setSubtitle(name)
        return true
      } catch (err) {
        setIsLive(false)
        const name = err instanceof DOMException ? err.name : ''
        let msg = 'Could not open webcam preview'
        if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
          msg = fromUserGesture
            ? 'Camera permission denied — enable it in the address bar'
            : 'Camera permission needed — tap the button below'
        } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
          msg = 'No webcam found'
        } else if (name === 'NotReadableError' || name === 'TrackStartError') {
          msg = 'Webcam is in use by another app — close Zoom/Meet and try again'
        } else if (!window.isSecureContext) {
          msg = explainCameraBlock()
        }
        setSubtitle(msg)
        return false
      }
    },
    [refreshCameras, stopSonyPreview, stopWebcamPreview, updateResBadge],
  )

  const startLivePreview = useCallback(
    async (fromUserGesture = false) => {
      if (!wantedRef.current || busy || startingRef.current) return false
      startingRef.current = true
      try {
        if (deviceIdRef.current === SONY_LIVEVIEW_ID) {
          return await startSonyLiveView()
        }
        return await startWebcamPreview(fromUserGesture)
      } finally {
        startingRef.current = false
      }
    },
    [busy, startSonyLiveView, startWebcamPreview],
  )

  const setWanted = useCallback(
    async (on: boolean, fromUserGesture = true) => {
      wantedRef.current = on
      setPreviewWanted(on)
      if (on) {
        await startLivePreview(fromUserGesture)
      } else {
        stopLivePreview()
        setSubtitle('Preview is off — tap to enable when needed')
      }
    },
    [startLivePreview, stopLivePreview],
  )

  const selectCamera = useCallback(
    async (deviceId: string) => {
      deviceIdRef.current = deviceId
      setSelectedDeviceId(deviceId)
      saveStoredDeviceId(deviceId)
      if (wantedRef.current) {
        await startLivePreview(true)
      }
    },
    [startLivePreview],
  )

  const onSonyStreamError = useCallback(() => {
    setIsLive(false)
    setIsSonyLive(false)
    setSonyStreamUrl('')
    setSubtitle('Sony live view failed — check USB / PC Remote, then enable Preview again')
  }, [])

  useEffect(() => {
    void refreshCameras()
    const onDeviceChange = () => {
      void refreshCameras()
    }
    navigator.mediaDevices?.addEventListener?.('devicechange', onDeviceChange)
    return () => {
      navigator.mediaDevices?.removeEventListener?.('devicechange', onDeviceChange)
    }
  }, [refreshCameras])

  useEffect(() => {
    void refreshCameras()
  }, [sonyConnected, refreshCameras])

  useEffect(() => {
    const onVis = () => {
      if (document.hidden) {
        stopLivePreview()
      } else if (wantedRef.current && !busy) {
        void startLivePreview(false)
      }
    }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      document.removeEventListener('visibilitychange', onVis)
      wantedRef.current = false
      stopLivePreview()
    }
  }, [busy, startLivePreview, stopLivePreview])

  const withPreviewPaused = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T> => {
      const resumeAfter = wantedRef.current
      const wasLive = !!streamRef.current || isSonyLive
      wantedRef.current = false
      setPreviewWanted(false)
      stopLivePreview()
      await new Promise((r) => setTimeout(r, wasLive ? 400 : 0))
      try {
        return await fn()
      } finally {
        wantedRef.current = resumeAfter
        setPreviewWanted(resumeAfter)
        if (resumeAfter) await startLivePreview(false)
      }
    },
    [isSonyLive, startLivePreview, stopLivePreview],
  )

  return {
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
    cameras,
    selectedDeviceId,
    selectCamera,
    refreshCameras,
  }
}
