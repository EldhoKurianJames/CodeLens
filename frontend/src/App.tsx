import { useState } from 'react'
import type { NavState } from './types'
import GalleryPage from './pages/GalleryPage'
import AnalyzerPage from './pages/AnalyzerPage'

export default function App() {
  const [nav, setNav] = useState<NavState>({ page: 'gallery' })

  if (nav.page === 'gallery') {
    return (
      <GalleryPage
        onCustomAnalyze={() => setNav({ page: 'analyzer', mode: 'custom' })}
        onGalleryItem={(id: string) => setNav({ page: 'analyzer', mode: 'gallery', galleryId: id })}
      />
    )
  }

  return (
    <AnalyzerPage
      mode={nav.mode}
      galleryId={nav.mode === 'gallery' ? nav.galleryId : undefined}
      onBack={() => setNav({ page: 'gallery' })}
    />
  )
}
