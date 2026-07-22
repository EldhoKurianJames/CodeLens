import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import { Play, Pause, SkipBack, SkipForward } from 'lucide-react'
import type { AccessLogEntry } from '../types'

interface Props {
  accessLog: AccessLogEntry[]
  numSets: number
}

export default function CacheHeatmap({ accessLog, numSets }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [step, setStep] = useState(accessLog.length - 1)
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    setStep(accessLog.length - 1)
    setPlaying(false)
  }, [accessLog])

  useEffect(() => {
    if (!playing) return
    if (step >= accessLog.length - 1) { setPlaying(false); return }
    const t = setTimeout(() => setStep(s => s + 1), 25)
    return () => clearTimeout(t)
  }, [playing, step, accessLog.length])

  useEffect(() => {
    const svg = d3.select(svgRef.current)
    const wrap = wrapRef.current
    if (!wrap || accessLog.length === 0) return

    svg.selectAll('*').remove()

    const ml = 32, mt = 22, mb = 24, mr = 8
    const W = wrap.clientWidth
    const cellH = Math.max(14, Math.min(22, (120 - mt - mb) / numSets))
    const H = numSets * cellH
    const innerW = W - ml - mr

    svg.attr('width', W).attr('height', H + mt + mb)

    const g = svg.append('g').attr('transform', `translate(${ml},${mt})`)

    const cellW = innerW / accessLog.length

    // Background row bands
    d3.range(numSets).forEach(si => {
      g.append('rect')
        .attr('x', 0).attr('y', si * cellH)
        .attr('width', innerW).attr('height', cellH)
        .attr('fill', si % 2 === 0 ? '#1c2128' : '#161b22')
    })

    // Access cells up to current step
    accessLog.slice(0, step + 1).forEach((entry, i) => {
      g.append('rect')
        .attr('x', i * cellW)
        .attr('y', entry.set_index * cellH + 1)
        .attr('width', Math.max(0.8, cellW - 0.3))
        .attr('height', cellH - 2)
        .attr('fill', entry.hit ? '#22c55e' : '#ef4444')
        .attr('opacity', i === step ? 1 : 0.75)
        .attr('rx', Math.min(1, cellW * 0.2))
    })

    // Current step cursor
    if (step < accessLog.length) {
      const cx = step * cellW + cellW / 2
      g.append('line')
        .attr('x1', cx).attr('x2', cx)
        .attr('y1', -mt + 4).attr('y2', H + 2)
        .attr('stroke', '#e6edf3')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '2,2')
        .attr('opacity', 0.6)
    }

    // Row labels
    d3.range(numSets).forEach(i => {
      g.append('text')
        .attr('x', -5).attr('y', i * cellH + cellH / 2)
        .attr('dy', '0.35em').attr('text-anchor', 'end')
        .attr('fill', '#484f58').attr('font-size', 9)
        .attr('font-family', 'JetBrains Mono, monospace')
        .text(`S${i}`)
    })

    // X-axis tick labels
    const tickEvery = Math.ceil(accessLog.length / 8)
    for (let i = 0; i < accessLog.length; i += tickEvery) {
      g.append('text')
        .attr('x', i * cellW).attr('y', H + 14)
        .attr('text-anchor', 'middle')
        .attr('fill', '#484f58').attr('font-size', 8)
        .attr('font-family', 'JetBrains Mono, monospace')
        .text(i)
    }
  }, [accessLog, step, numSets])

  const cur = accessLog[step]

  return (
    <div className="rounded-2xl bg-[#161b22] ring-1 ring-white/[0.06] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 pt-4 pb-3">
        <p className="text-sm font-medium text-[#e6edf3]">Memory Access Heatmap</p>
        <div className="flex items-center gap-3">
          {cur && (
            <span className={`text-xs font-mono px-2 py-0.5 rounded-full ${
              cur.hit ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
            }`}>
              {cur.hit ? 'HIT' : 'MISS'} · set {cur.set_index}
            </span>
          )}
          <div className="flex items-center gap-2 text-[11px] text-[#8b949e]">
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-green-500/70" />hit</span>
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-red-500/70" />miss</span>
          </div>
        </div>
      </div>

      {/* Heatmap SVG */}
      <div ref={wrapRef} className="w-full px-1">
        <svg ref={svgRef} className="w-full" />
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2 px-4 pb-4 pt-1">
        <button
          onClick={() => { setStep(0); setPlaying(false) }}
          className="p-1.5 rounded-lg text-[#484f58] hover:text-[#8b949e] hover:bg-white/[0.04] transition-colors"
        >
          <SkipBack size={12} />
        </button>
        <button
          onClick={() => {
            if (step >= accessLog.length - 1) { setStep(0); setPlaying(true) }
            else setPlaying(p => !p)
          }}
          className="p-1.5 rounded-lg bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600/30 transition-colors"
        >
          {playing ? <Pause size={13} /> : <Play size={13} />}
        </button>
        <button
          onClick={() => { setStep(accessLog.length - 1); setPlaying(false) }}
          className="p-1.5 rounded-lg text-[#484f58] hover:text-[#8b949e] hover:bg-white/[0.04] transition-colors"
        >
          <SkipForward size={12} />
        </button>
        <input
          type="range" min={0} max={accessLog.length - 1} value={step}
          onChange={e => { setStep(parseInt(e.target.value)); setPlaying(false) }}
          className="flex-1 h-0.5"
        />
        <span className="text-[11px] font-mono text-[#484f58] shrink-0">
          {step + 1}<span className="text-[#30363d]">/{accessLog.length}</span>
        </span>
      </div>
    </div>
  )
}
