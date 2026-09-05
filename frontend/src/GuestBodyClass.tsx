import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

export function GuestBodyClass() {
  const location = useLocation()
  useEffect(() => {
    const isGuest = location.pathname.startsWith('/photo/')
    const isRemote = location.pathname.startsWith('/remote')
    document.body.classList.toggle('guest', isGuest)
    document.body.classList.toggle('remote', isRemote)
    if (isRemote) {
      document.title = 'Remote · Photobooth'
    } else if (!isGuest) {
      document.title = 'Thermal Photobooth'
    }
    return () => {
      document.body.classList.remove('guest')
      document.body.classList.remove('remote')
      document.body.classList.remove('is-reprint-open')
    }
  }, [location.pathname])
  return null
}
