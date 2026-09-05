export type DotKind = 'ok' | 'warn' | 'err' | 'muted'

export type DeviceInfo = {
  connected?: boolean
  model?: string
  error?: string
  backend?: string
  enabled?: boolean
}

export type StatusResponse = {
  cameras?: {
    gphoto?: DeviceInfo
    webcam?: DeviceInfo
  }
  printer?: DeviceInfo
  cloudinary?: DeviceInfo
  remote?: DeviceInfo & { clients?: number }
  last_print?: {
    photo_id?: string
    layout_url?: string
    photo_url?: string
    captured_at?: string
  } | null
}

export type CaptureResult = {
  ok?: boolean
  photo_id: string
  printed?: boolean
  qr_url?: string
  cloudinary_url?: string
  cloudinary_photo_url?: string
  cloudinary_layout_url?: string
  layout_url: string
  layout_color_url?: string
  photo_url: string
  frame_urls?: string[]
  message?: string
  captured_at?: string
}

export type GuestPhotoAssets = {
  photo_id: string
  photo_url: string
  layout_url: string | null
  photo_url_local?: string | null
  layout_url_local?: string | null
  cloudinary_photo_url?: string | null
  cloudinary_layout_url?: string | null
}

export type DitherStyle = 'floyd' | 'comic'
export type CaptureSource = 'gphoto' | 'webcam'

export type RecentPrint = {
  photo_id: string
  layout_color_url: string
  layout_url?: string | null
  photo_url?: string | null
  captured_at?: string | null
}

export type CapturePhase =
  | 'idle'
  | 'countdown'
  | 'capturing'
  | 'processing'
  | 'linking'
  | 'uploading'
  | 'printing'
  | 'done'
  | 'error'

export type CaptureProgress = {
  phase: CapturePhase | string
  label?: string
  updated_at?: number
}

export type CaptureOverlayState =
  | { mode: 'countdown'; count: 3 | 2 | 1 }
  | { mode: 'phase'; phase: CapturePhase; label: string }
  | null

export type AppConfig = {
  org_name: string
  cloudinary_enabled: boolean
  cloudinary_folder: string
}

export type SelfboothInfo = {
  remote_url: string | null
  lan_ip: string | null
  port: number
}
