import type { AppConfig, CaptureResult, CaptureSource, DitherStyle, GuestPhotoAssets, StatusResponse } from '../types'

async function readError(res: Response): Promise<string> {
  const data = await res.json().catch(() => ({} as { detail?: string }))
  return data.detail || res.statusText || 'Lỗi không xác định'
}

export async function fetchStatus(): Promise<StatusResponse> {
  const res = await fetch('/api/status')
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function fetchConfig(): Promise<AppConfig> {
  const res = await fetch('/api/config')
  if (!res.ok) {
    return {
      org_name: 'BK FIRE',
      cloudinary_enabled: false,
      cloudinary_folder: '',
    }
  }
  return res.json()
}

export async function fetchPhotoAssets(photoId: string): Promise<GuestPhotoAssets> {
  const res = await fetch(`/api/photo/${encodeURIComponent(photoId)}`)
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function capturePrint(
  source: CaptureSource,
  ditherStyle: DitherStyle,
): Promise<CaptureResult> {
  const body = new FormData()
  body.append('source', source)
  body.append('dither_style', ditherStyle)
  const res = await fetch('/api/capture-print', { method: 'POST', body })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || res.statusText || 'Lỗi không xác định')
  return data as CaptureResult
}

export async function reprintLast(
  ditherStyle: DitherStyle,
  copies: number,
): Promise<CaptureResult> {
  const body = new FormData()
  body.append('dither_style', ditherStyle)
  body.append('copies', String(copies))
  const res = await fetch('/api/reprint-last', { method: 'POST', body })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || res.statusText || 'Lỗi không xác định')
  return data as CaptureResult
}
