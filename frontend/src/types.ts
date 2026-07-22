export interface AccessLogEntry {
  address: number
  block_address: number
  set_index: number
  tag: number
  hit: boolean
}

export interface CacheStats {
  hits: number
  misses: number
  total_accesses: number
  hit_rate: number
  miss_rate: number
  cache_size_bytes: number
  block_size_bytes: number
  associativity: number
  num_sets: number
}

export interface AIExplanation {
  explanation: string
  model: string | null
  cached: boolean
  error: boolean
  error_type?: string
}

export interface AnalysisResult {
  analysis_mode: string
  total_addresses_traced: number
  cache_stats: CacheStats
  access_log: AccessLogEntry[]
  metadata: Record<string, unknown>
  pattern: {
    kind: string
    description: string
    array_name: string
  }
  ai_explanation?: AIExplanation
}

export interface CacheConfig {
  size_bytes: number
  block_size_bytes: number
  associativity: number
}

export interface GalleryVariantResult {
  cache_stats: CacheStats
  access_log: AccessLogEntry[]
  metadata: Record<string, unknown>
  pattern: { kind: string; description: string; array_name: string }
  analysis_mode: string
  total_addresses_traced: number
}

export interface GalleryVariant {
  label: string
  code: string
  result: GalleryVariantResult
  metadata: Record<string, unknown>
}

export interface GalleryItem {
  id: string
  title: string
  description: string
  variants: GalleryVariant[]
}

export type LoadingStage = 'idle' | 'simulating' | 'explaining' | 'done' | 'error'

export type NavState =
  | { page: 'gallery' }
  | { page: 'analyzer'; mode: 'custom' }
  | { page: 'analyzer'; mode: 'gallery'; galleryId: string }
