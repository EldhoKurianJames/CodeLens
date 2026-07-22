import { useEffect, useState } from 'react'
import { Cpu, ArrowRight, Zap, GitCompare, Loader2, AlertCircle } from 'lucide-react'
import { fetchGallery } from '../api'
import type { GalleryItem } from '../types'

interface Props {
  onCustomAnalyze: () => void
  onGalleryItem: (id: string) => void
}

function HitBadge({ rate }: { rate: number }) {
  const pct = (rate * 100).toFixed(1)
  const color = rate >= 0.75 ? 'text-green-400 bg-green-500/10 border-green-500/20'
    : rate >= 0.4 ? 'text-amber-400 bg-amber-500/10 border-amber-500/20'
    : 'text-red-400 bg-red-500/10 border-red-500/20'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-mono font-semibold ${color}`}>
      {pct}%
    </span>
  )
}

function GalleryCard({ item, onClick }: { item: GalleryItem; onClick: () => void }) {
  const [a, b] = item.variants
  const aRate = a?.result?.cache_stats?.hit_rate ?? 0
  const bRate = b?.result?.cache_stats?.hit_rate ?? 0

  return (
    <button
      onClick={onClick}
      className="group rounded-2xl bg-[#161b22] ring-1 ring-white/[0.06] p-5 text-left transition-all hover:ring-indigo-500/30 hover:bg-[#1a2035] hover:shadow-xl hover:shadow-indigo-500/5 focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <h3 className="font-semibold text-[#e6edf3] group-hover:text-white transition-colors">
          {item.title}
        </h3>
        <ArrowRight size={16} className="text-[#484f58] group-hover:text-indigo-400 group-hover:translate-x-0.5 transition-all shrink-0 mt-0.5" />
      </div>

      <p className="text-xs text-[#8b949e] mb-4 leading-relaxed">{item.description}</p>

      {a && b && (
        <div className="flex items-center gap-2">
          <div className="flex-1 rounded-lg bg-[#21262d] px-3 py-2 text-center">
            <p className="text-[10px] text-[#8b949e] mb-1 truncate">{a.label}</p>
            <HitBadge rate={aRate} />
          </div>
          <div className="flex items-center justify-center">
            <GitCompare size={12} className="text-[#484f58]" />
          </div>
          <div className="flex-1 rounded-lg bg-[#21262d] px-3 py-2 text-center">
            <p className="text-[10px] text-[#8b949e] mb-1 truncate">{b.label}</p>
            <HitBadge rate={bRate} />
          </div>
        </div>
      )}
    </button>
  )
}

export default function GalleryPage({ onCustomAnalyze, onGalleryItem }: Props) {
  const [items, setItems] = useState<GalleryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchGallery()
      .then(setItems)
      .catch(e => setError((e as Error).message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-[#0d1117]">
      {/* Navbar */}
      <nav className="border-b border-white/[0.06] bg-[#0d1117]/90 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 h-13 flex items-center gap-3">
          <Cpu size={16} className="text-indigo-400" />
          <span className="font-semibold text-[#e6edf3] tracking-tight text-sm">CacheLens AI</span>
          <span className="w-px h-4 bg-white/[0.08]" />
          <span className="text-xs text-[#484f58]">Cache Simulator</span>
        </div>
      </nav>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-4 sm:px-6 pt-16 pb-12">
        <div className="max-w-2xl">
          <h1 className="text-4xl sm:text-5xl font-bold text-[#e6edf3] leading-tight mb-4 tracking-tight">
            Same time complexity.<br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-violet-400">
              Wildly different performance.
            </span>
          </h1>
          <p className="text-[15px] text-[#8b949e] mb-8 leading-relaxed max-w-lg">
            Simulate cache behaviour in your Python code and understand{' '}
            <span className="text-[#c9d1d9]">why</span> certain access patterns are 15× slower — with AI-powered explanations.
          </p>
          <button
            onClick={onCustomAnalyze}
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 px-5 py-2.5 text-sm font-medium text-white transition-colors shadow-xl shadow-indigo-500/25"
          >
            <span>Analyze Your Own Code</span>
            <ArrowRight size={14} />
          </button>
        </div>
      </section>

      {/* Gallery */}
      <section className="mx-auto max-w-6xl px-4 sm:px-6 pb-20">
        <h2 className="text-sm font-medium text-[#8b949e] mb-5">
          Algorithm comparisons
        </h2>

        {loading && (
          <div className="flex items-center gap-3 text-[#8b949e]">
            <Loader2 size={16} className="animate-spin" />
            <span className="text-sm">Loading gallery…</span>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
            <AlertCircle size={16} />
            <span>Could not load gallery: {error}. Is the backend running?</span>
          </div>
        )}

        {!loading && !error && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map(item => (
              <GalleryCard
                key={item.id}
                item={item}
                onClick={() => onGalleryItem(item.id)}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
