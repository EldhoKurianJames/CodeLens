import type { AnalysisResult, CacheConfig, GalleryItem } from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'
const API_KEY = import.meta.env.VITE_API_KEY ?? ''

// All /api/v1/* routes are protected by an X-API-Key header on the backend
// (see backend/main.py's require_api_key dependency). If VITE_API_KEY is
// unset the header is simply omitted, which only works against a backend
// that also has no API_KEY configured (local/dev mode).
function authHeaders(): Record<string, string> {
  return API_KEY ? { 'X-API-Key': API_KEY } : {}
}

async function parseErrorBody(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}))
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI/Pydantic validation error shape: [{loc, msg, type}, ...]
    return detail.map(d => (d as { msg?: string }).msg ?? JSON.stringify(d)).join('; ')
  }
  return `HTTP ${res.status}`
}

export async function analyzeCode(
  code: string,
  cacheConfig: CacheConfig,
  includeAI = false,
): Promise<AnalysisResult> {
  const res = await fetch(`${BASE}/api/v1/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      code,
      cache_config: cacheConfig,
      include_ai_explanation: includeAI,
    }),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return res.json() as Promise<AnalysisResult>
}

export async function fetchGallery(): Promise<GalleryItem[]> {
  const res = await fetch(`${BASE}/api/v1/gallery`, { headers: authHeaders() })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return res.json() as Promise<GalleryItem[]>
}

export async function fetchGalleryItem(id: string): Promise<GalleryItem> {
  const res = await fetch(`${BASE}/api/v1/gallery/${id}`, { headers: authHeaders() })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  return res.json() as Promise<GalleryItem>
}
