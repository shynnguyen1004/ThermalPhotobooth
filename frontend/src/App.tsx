import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { KioskPage } from './pages/KioskPage'
import { PhotoPage } from './pages/PhotoPage'

function GuestBodyClass() {
  const location = useLocation()
  useEffect(() => {
    const isGuest = location.pathname.startsWith('/photo/')
    document.body.classList.toggle('guest', isGuest)
    return () => document.body.classList.remove('guest')
  }, [location.pathname])
  return null
}

export default function App() {
  return (
    <BrowserRouter>
      <GuestBodyClass />
      <Routes>
        <Route path="/" element={<KioskPage />} />
        <Route path="/photo/:photoId" element={<PhotoPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
