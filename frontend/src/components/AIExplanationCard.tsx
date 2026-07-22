import type { AIExplanation } from '../types'
import { Sparkles, AlertCircle, Loader2 } from 'lucide-react'

interface Props {
  explanation: AIExplanation | null
  loading: boolean
}

export default function AIExplanationCard({ explanation, loading }: Props) {
  return (
    <div className="rounded-2xl bg-[#161b22] ring-1 ring-white/[0.06] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-5 pt-4 pb-3">
        <div className="p-1.5 rounded-lg bg-indigo-500/10">
          <Sparkles size={13} className="text-indigo-400" />
        </div>
        <span className="text-sm font-medium text-[#e6edf3]">AI Analysis</span>
        <div className="ml-auto flex items-center gap-2">
          {explanation?.cached && (
            <span className="text-[10px] font-mono text-[#484f58] bg-white/[0.04] rounded px-1.5 py-0.5">cached</span>
          )}
          {explanation?.model && (
            <span className="text-[10px] font-mono text-[#484f58]">{explanation.model.split('-').slice(0, 3).join('-')}</span>
          )}
        </div>
      </div>

      <div className="border-t border-white/[0.04] px-5 py-4">
        {loading && (
          <div className="flex items-center gap-3 text-[#8b949e]">
            <Loader2 size={15} className="animate-spin text-indigo-400 shrink-0" />
            <span className="text-sm">Generating explanation with Claude…</span>
          </div>
        )}

        {!loading && explanation?.error && (
          <div className="flex items-start gap-3">
            <AlertCircle size={15} className="text-amber-400 shrink-0 mt-0.5" />
            <span className="text-sm text-[#8b949e]">AI explanation unavailable — simulation results shown above.</span>
          </div>
        )}

        {!loading && explanation && !explanation.error && (
          <p className="text-sm text-[#c9d1d9] leading-7 animate-fade-in">
            {explanation.explanation}
          </p>
        )}

        {!loading && !explanation && (
          <p className="text-sm text-[#484f58]">Run an analysis to generate an explanation.</p>
        )}
      </div>
    </div>
  )
}
