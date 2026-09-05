import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import TargetCursor from './components/TargetCursor'
import { TargetCursorProvider, useTargetCursor } from './context/TargetCursorContext'
import { KioskPage } from './pages/KioskPage'
import { PhotoPage } from './pages/PhotoPage'
import { RemotePage } from './pages/RemotePage'
import { GuestBodyClass } from './GuestBodyClass'

const CURSOR_TARGETS = [
  '.btn:not(:disabled)',
  '.enable-cam',
  '.preview-toggle',
  '.history-card:not(:disabled)',
  '.style-chip__opt',
  '.cta',
  '.cursor-toggle',
  '.print-toggle:not(:disabled)',
  '.copies-chip--rail',
].join(', ')

function TargetCursorLayer() {
  const location = useLocation()
  const { enabled } = useTargetCursor()
  const showCursor = enabled && !location.pathname.startsWith('/remote')
  return (
    <TargetCursor
      enabled={showCursor}
      targetSelector={CURSOR_TARGETS}
      spinDuration={2}
      hideDefaultCursor
      parallaxOn
      cursorColor="#ffffff"
      cursorColorOnTarget="#3084C6"
    />
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <TargetCursorProvider>
        <TargetCursorLayer />
        <GuestBodyClass />
        <Routes>
          <Route path="/" element={<KioskPage />} />
          <Route path="/remote" element={<RemotePage />} />
          <Route path="/photo/:photoId" element={<PhotoPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </TargetCursorProvider>
    </BrowserRouter>
  )
}
