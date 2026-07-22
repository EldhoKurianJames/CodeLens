import type { AnalysisResult, CacheConfig, GalleryItem } from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

export async function analyzeCode(
  code: string,
  cacheConfig: CacheConfig,
  includeAI = true,
): Promise<AnalysisResult> {
  const res = await fetch(`${BASE}/api/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      code,
      cache_config: cacheConfig,
      include_ai_explanation: includeAI,
    }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<AnalysisResult>
}

export async function fetchGallery(): Promise<GalleryItem[]> {
  const res = await fetch(`${BASE}/api/gallery`)
  if (!res.ok) throw new Error('Failed to load gallery')
  return res.json() as Promise<GalleryItem[]>
}

export async function fetchGalleryItem(id: string): Promise<GalleryItem> {
  const res = await fetch(`${BASE}/api/gallery/${id}`)
  if (!res.ok) throw new Error('Gallery item not found')
  return res.json() as Promise<GalleryItem>
}
