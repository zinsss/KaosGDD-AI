import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { registerSW } from 'virtual:pwa-register'
import App from './App'
import './styles.css'

const updateSW = registerSW({
  onNeedRefresh() {
    window.dispatchEvent(new CustomEvent('roun-update', { detail: updateSW }))
  },
})

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
