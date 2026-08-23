import { useCallback, useEffect, useRef, useState } from 'react'

function cameraApiAvailable() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
}

export function explainCameraBlock() {
  if (!window.isSecureContext) {
    return 'Mở qua http://127.0.0.1:5173 hoặc :8000 (localhost) để dùng Camera'
  }
  if (!cameraApiAvailable()) {
    return 'Trình duyệt hiện không mở được Camera API'
  }
  return 'Bấm “Cho phép Camera” để hiện hộp thoại quyền'
}

export function useLivePreview(busy: boolean) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const wantedRef = useRef(false)
  const startingRef = useRef(false)

  const [previewWanted, setPreviewWanted] = useState(false)
  const [isLive, setIsLive] = useState(false)
  const [subtitle, setSubtitle] = useState('Preview đang tắt — bấm để bật khi cần')
  const [resBadge, setResBadge] = useState('—')

  const updateResBadge = useCallback(() => {
    const video = videoRef.current
    if (!video?.videoWidth) {
      setResBadge('—')
      return
    }
    const long = Math.max(video.videoWidth, video.videoHeight)
    setResBadge(long >= 1800 ? '1080p' : long >= 1200 ? '720p' : `${video.videoWidth}×${video.videoHeight}`)
  }, [])

  const stopLivePreview = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setIsLive(false)
    setResBadge('—')
  }, [])

  const startLivePreview = useCallback(
    async (fromUserGesture = false) => {
      if (!wantedRef.current || busy || startingRef.current) return false
      if (streamRef.current) return true
      if (!cameraApiAvailable()) {
        setSubtitle(explainCameraBlock())
        return false
      }

      startingRef.current = true
      setSubtitle(fromUserGesture ? 'Đang yêu cầu quyền Camera…' : 'Đang kết nối webcam…')
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            facingMode: 'user',
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
        })
        if (!wantedRef.current) {
          stream.getTracks().forEach((t) => t.stop())
          return false
        }
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play().catch(() => {})
        }
        setIsLive(true)
        updateResBadge()
        setSubtitle('Live preview')
        return true
      } catch (err) {
        setIsLive(false)
        const name = err instanceof DOMException ? err.name : ''
        let msg = 'Không mở được webcam preview'
        if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
          msg = fromUserGesture
            ? 'Bạn đã từ chối Camera — hãy bật lại trong thanh địa chỉ'
            : 'Cần cho phép Camera — bấm nút bên dưới'
        } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
          msg = 'Không tìm thấy webcam'
        } else if (name === 'NotReadableError' || name === 'TrackStartError') {
          msg = 'Webcam đang bị app khác giữ — đóng Zoom/Meet rồi thử lại'
        } else if (!window.isSecureContext) {
          msg = explainCameraBlock()
        }
        setSubtitle(msg)
        return false
      } finally {
        startingRef.current = false
      }
    },
    [busy, updateResBadge],
  )

  const setWanted = useCallback(
    async (on: boolean, fromUserGesture = true) => {
      wantedRef.current = on
      setPreviewWanted(on)
      if (on) {
        await startLivePreview(fromUserGesture)
      } else {
        stopLivePreview()
        setSubtitle('Preview đang tắt — bấm để bật khi cần')
      }
    },
    [startLivePreview, stopLivePreview],
  )

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
      const wasLive = !!streamRef.current
      wantedRef.current = false
      setPreviewWanted(false)
      stopLivePreview()
      await new Promise((r) => setTimeout(r, wasLive ? 350 : 0))
      try {
        return await fn()
      } finally {
        wantedRef.current = resumeAfter
        setPreviewWanted(resumeAfter)
        if (resumeAfter) await startLivePreview(false)
      }
    },
    [startLivePreview, stopLivePreview],
  )

  return {
    videoRef,
    previewWanted,
    isLive,
    subtitle,
    setSubtitle,
    resBadge,
    setWanted,
    updateResBadge,
    withPreviewPaused,
  }
}
