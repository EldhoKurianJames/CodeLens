import { useEffect, useState, Suspense, lazy } from 'react'
import { Cpu, ArrowLeft, Play, Loader2, AlertCircle, Code2, Sparkles } from 'lucide-react'
import { analyzeCode, fetchGalleryItem } from '../api'
import type { AnalysisResult, CacheConfig, GalleryItem, LoadingStage } from '../types'
import StatsCard from '../components/StatsCard'
import CacheHeatmap from '../components/CacheHeatmap'
import HitRateChart from '../components/HitRateChart'
import AIExplanationCard from '../components/AIExplanationCard'
import CacheConfigPanel from '../components/CacheConfigPanel'
import EducationalSidebar from '../components/EducationalSidebar'

const MonacoEditor = lazy(() => import('@monaco-editor/react'))

function AIToggle({ enabled, onChange }: { enabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!enabled)}
      title={enabled ? 'AI explanation ON — click to disable' : 'AI explanation OFF — click to enable'}
      className={`flex items-center gap-2 rounded-xl px-3 py-2.5 text-xs font-medium transition-all ring-1 ${
        enabled
          ? 'bg-indigo-600/15 text-indigo-300 ring-indigo-500/30 hover:bg-indigo-600/25'
          : 'bg-white/[0.04] text-[#484f58] ring-white/[0.06] hover:text-[#8b949e] hover:bg-white/[0.06]'
      }`}
    >
      <Sparkles size={13} />
      <span>AI {enabled ? 'on' : 'off'}</span>
    </button>
  )
}

const DEFAULT_CODE = `arr = [[0]*64 for _ in range(64)]
for i in range(64):
    for j in range(64):
        arr[i][j] = i + j
`

const DEFAULT_CONFIG: CacheConfig = { size_bytes: 512, block_size_bytes: 64, associativity: 2 }

interface Props {
  mode: 'custom' | 'gallery'
  galleryId?: string
  onBack: () => void
}

interface VariantResult {
  label: string
  code: string
  result: AnalysisResult | null
  aiLoading: boolean
}

function ResultsColumn({ vr }: { vr: VariantResult; config: CacheConfig }) {
  if (!vr.result) return null
  const { result } = vr
  return (
    <div className="space-y-4 animate-slide-up">
      <StatsCard stats={result.cache_stats} label={vr.label} />
      {result.access_log.length > 0 && (
        <CacheHeatmap accessLog={result.access_log} numSets={result.cache_stats.num_sets} />
      )}
      {result.access_log.length > 0 && (
        <HitRateChart accessLog={result.access_log} finalHitRate={result.cache_stats.hit_rate} />
      )}
      <AIExplanationCard explanation={result.ai_explanation ?? null} loading={vr.aiLoading} />
    </div>
  )
}

export default function AnalyzerPage({ mode, galleryId, onBack }: Props) {
  const [code, setCode] = useState(DEFAULT_CODE)
  const [config, setConfig] = useState<CacheConfig>(DEFAULT_CONFIG)
  const [stage, setStage] = useState<LoadingStage>('idle')
  const [error, setError] = useState<string | null>(null)

  const [useAI, setUseAI] = useState(false)

  const [galleryItem, setGalleryItem] = useState<GalleryItem | null>(null)
  const [galleryLoading, setGalleryLoading] = useState(false)

  const [variants, setVariants] = useState<VariantResult[]>([])
  const [customResult, setCustomResult] = useState<AnalysisResult | null>(null)

  useEffect(() => {
    if (mode !== 'gallery' || !galleryId) return
    setGalleryLoading(true)
    fetchGalleryItem(galleryId)
      .then(item => {
        setGalleryItem(item)
        const initial: VariantResult[] = item.variants.map(v => ({
          label: v.label,
          code: v.code,
          result: v.result as unknown as AnalysisResult,
          aiLoading: false,
        }))
        setVariants(initial)
      })
      .catch(e => setError((e as Error).message))
      .finally(() => setGalleryLoading(false))
  }, [mode, galleryId])

  async function runGalleryAI() {
    if (!galleryItem) return
    setVariants(prev => prev.map(v => ({ ...v, aiLoading: true })))
    const updated = await Promise.all(
      galleryItem.variants.map(async (v, i) => {
        try {
          const res = await analyzeCode(v.code, config, useAI)
          return { ...variants[i], result: res, aiLoading: false }
        } catch {
          return { ...variants[i], aiLoading: false }
        }
      })
    )
    setVariants(updated)
  }

  async function runCustomAnalysis() {
    setStage('simulating')
    setError(null)
    setCustomResult(null)
    try {
      const timer = setTimeout(() => setStage('explaining'), 500)
      const result = await analyzeCode(code, config, useAI)
      clearTimeout(timer)
      setCustomResult(result)
      setStage('done')
    } catch (e) {
      setError((e as Error).message)
      setStage('error')
    }
  }

  const isRunning = stage === 'simulating' || stage === 'explaining'

  return (
    <div className="min-h-screen bg-[#0d1117]">
      {/* Navbar */}
      <nav className="border-b border-white/[0.06] bg-[#0d1117]/90 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 h-13 flex items-center gap-3">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-sm text-[#484f58] hover:text-[#8b949e] transition-colors mr-1"
          >
            <ArrowLeft size={14} />
            <span>Back</span>
          </button>
          <span className="w-px h-4 bg-white/[0.08]" />
          <Cpu size={15} className="text-indigo-400" />
          <span className="font-semibold text-[#e6edf3] tracking-tight text-sm">CacheLens AI</span>
          {galleryItem && (
            <>
              <span className="w-px h-4 bg-white/[0.08]" />
              <span className="text-sm text-[#8b949e]">{galleryItem.title}</span>
            </>
          )}
          {mode === 'custom' && (
            <>
              <span className="w-px h-4 bg-white/[0.08]" />
              <span className="text-sm text-[#8b949e]">Analyzer</span>
            </>
          )}
        </div>
      </nav>

      <div className="mx-auto max-w-7xl px-4 sm:px-6 py-6 space-y-6">

        {/* ── GALLERY MODE ─────────────────────────────────────────── */}
        {mode === 'gallery' && (
          <>
            {galleryLoading && (
              <div className="flex items-center gap-3 text-[#8b949e] py-12 justify-center">
                <Loader2 size={18} className="animate-spin" />
                <span>Loading gallery item…</span>
              </div>
            )}

            {galleryItem && (
              <div className="space-y-4">
                <div className="flex items-start justify-between flex-wrap gap-4 pb-2">
                  <div>
                    <h1 className="text-2xl font-bold text-[#e6edf3] tracking-tight">{galleryItem.title}</h1>
                    <p className="text-sm text-[#8b949e] mt-1">{galleryItem.description}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <AIToggle enabled={useAI} onChange={setUseAI} />
                    <button
                      onClick={runGalleryAI}
                      disabled={variants.some(v => v.aiLoading) || !useAI}
                      className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white transition-colors shadow-lg shadow-indigo-500/20"
                    >
                      {variants.some(v => v.aiLoading) ? (
                        <><Loader2 size={13} className="animate-spin" /><span>Generating…</span></>
                      ) : (
                        <><Play size={13} /><span>Generate AI explanations</span></>
                      )}
                    </button>
                  </div>
                </div>

                {/* Code snippets (read-only) */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {galleryItem.variants.map((v) => (
                    <div key={v.label} className="rounded-2xl bg-[#161b22] ring-1 ring-white/[0.06] overflow-hidden">
                      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.04]">
                        <Code2 size={12} className="text-[#484f58]" />
                        <span className="text-sm font-medium text-[#e6edf3]">{v.label}</span>
                      </div>
                      <pre className="p-4 text-[13px] font-mono text-[#c9d1d9] overflow-x-auto leading-relaxed whitespace-pre">
                        {v.code}
                      </pre>
                    </div>
                  ))}
                </div>

                {/* Results */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {variants.map((vr) => (
                    <ResultsColumn key={vr.label} vr={vr} config={config} />
                  ))}
                </div>

                <EducationalSidebar />
              </div>
            )}
          </>
        )}

        {/* ── CUSTOM MODE ──────────────────────────────────────────── */}
        {mode === 'custom' && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {/* Left panel: editor + config + button */}
            <div className="space-y-4">
              <div className="rounded-2xl bg-[#161b22] ring-1 ring-white/[0.06] overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.04]">
                  <Code2 size={13} className="text-[#484f58]" />
                  <span className="text-sm font-medium text-[#e6edf3]">Python code</span>
                  <span className="ml-auto text-[11px] text-[#484f58]">loops · array access only</span>
                </div>
                <Suspense fallback={<div className="h-72 flex items-center justify-center text-[#8b949e] text-sm"><Loader2 size={16} className="animate-spin mr-2" />Loading editor…</div>}>
                  <MonacoEditor
                    height="300px"
                    defaultLanguage="python"
                    value={code}
                    onChange={v => setCode(v ?? '')}
                    theme="vs-dark"
                    options={{
                      fontSize: 13,
                      fontFamily: '"JetBrains Mono", monospace',
                      minimap: { enabled: false },
                      scrollBeyondLastLine: false,
                      lineNumbers: 'on',
                      padding: { top: 12, bottom: 12 },
                      wordWrap: 'on',
                    }}
                  />
                </Suspense>
              </div>

              <CacheConfigPanel config={config} onChange={setConfig} disabled={isRunning} />

              <div className="flex items-center gap-3">
                <button
                  onClick={runCustomAnalysis}
                  disabled={isRunning || !code.trim()}
                  className="flex-1 inline-flex items-center justify-center gap-2 rounded-2xl bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed px-5 py-3 text-sm font-semibold text-white transition-all shadow-xl shadow-indigo-500/20"
                >
                  {stage === 'simulating' && <><Loader2 size={14} className="animate-spin" /><span>Simulating…</span></>}
                  {stage === 'explaining' && <><Loader2 size={14} className="animate-spin" /><span>Asking Claude…</span></>}
                  {(stage === 'idle' || stage === 'done' || stage === 'error') && <><Play size={14} /><span>Analyze</span></>}
                </button>
                <AIToggle enabled={useAI} onChange={setUseAI} />
              </div>

              {error && (
                <div className="flex items-start gap-3 rounded-2xl bg-red-500/8 ring-1 ring-red-500/20 px-4 py-3 text-sm text-red-400 animate-fade-in">
                  <AlertCircle size={15} className="shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}

              <EducationalSidebar />
            </div>

            {/* Right panel: results */}
            <div>
              {customResult ? (
                <ResultsColumn
                  vr={{ label: 'Results', code, result: customResult, aiLoading: false }}
                  config={config}
                />
              ) : (
                <div className="flex flex-col items-center justify-center h-full min-h-[440px] rounded-2xl ring-1 ring-dashed ring-white/[0.06] text-[#484f58]">
                  <div className="p-4 rounded-2xl bg-white/[0.02] mb-4">
                    <Cpu size={28} className="opacity-30" />
                  </div>
                  <p className="text-sm text-[#8b949e]">Results will appear here</p>
                  <p className="text-xs mt-1 text-[#484f58]">Press Analyze to run simulation</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
