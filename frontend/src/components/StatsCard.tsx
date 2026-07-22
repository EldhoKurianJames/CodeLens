import type { CacheStats } from '../types'

interface Props {
  stats: CacheStats
  label?: string
}

function fmt(n: number) {
  return n.toLocaleString()
}

export default function StatsCard({ stats, label }: Props) {
  const hitPct = stats.hit_rate * 100
  const hitColor = hitPct >= 75 ? '#22c55e' : hitPct >= 40 ? '#f59e0b' : '#ef4444'

  return (
    <div className="rounded-2xl bg-[#161b22] ring-1 ring-white/[0.06] overflow-hidden">
      {/* Header strip */}
      <div className="px-6 pt-5 pb-4">
        {label && (
          <p className="text-xs text-[#8b949e] mb-4 font-medium">{label}</p>
        )}

        {/* Big number */}
        <div className="flex items-center justify-between gap-4">
          <div>
            <p
              className="text-6xl font-mono font-bold tabular-nums leading-none tracking-tight"
              style={{ color: hitColor }}
            >
              {(hitPct).toFixed(2)}
              <span className="text-3xl">%</span>
            </p>
            <p className="text-sm text-[#8b949e] mt-2">cache hit rate</p>
          </div>

          {/* Donut-style ring */}
          <svg width="64" height="64" viewBox="0 0 64 64" className="shrink-0">
            <circle cx="32" cy="32" r="26" fill="none" stroke="#21262d" strokeWidth="6" />
            <circle
              cx="32" cy="32" r="26" fill="none"
              stroke={hitColor} strokeWidth="6"
              strokeDasharray={`${(hitPct / 100) * 163.4} 163.4`}
              strokeLinecap="round"
              transform="rotate(-90 32 32)"
              style={{ transition: 'stroke-dasharray 0.8s ease' }}
            />
          </svg>
        </div>

        {/* Progress bar */}
        <div className="mt-4 h-1 rounded-full bg-[#21262d] overflow-hidden">
          <div
            className="h-1 rounded-full transition-all duration-700"
            style={{ width: `${hitPct}%`, background: hitColor }}
          />
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 divide-x divide-white/[0.06] border-t border-white/[0.06]">
        {[
          { value: `${(100 - hitPct).toFixed(2)}%`, label: 'miss rate', muted: true },
          { value: fmt(stats.hits),   label: 'hits',   muted: false },
          { value: fmt(stats.misses), label: 'misses', muted: false },
        ].map(({ value, label: l, muted }) => (
          <div key={l} className="px-4 py-3 text-center">
            <p className={`text-sm font-mono font-semibold tabular-nums ${muted ? 'text-[#8b949e]' : 'text-[#e6edf3]'}`}>{value}</p>
            <p className="text-[11px] text-[#8b949e] mt-0.5">{l}</p>
          </div>
        ))}
      </div>

      {/* Config strip */}
      <div className="flex items-center gap-4 px-6 py-3 bg-[#0d1117]/40 border-t border-white/[0.04]">
        {[
          ['cache', `${stats.cache_size_bytes >= 1024 ? stats.cache_size_bytes/1024+'KB' : stats.cache_size_bytes+'B'}`],
          ['block', `${stats.block_size_bytes}B`],
          [`${stats.associativity}-way`, ''],
          [`${stats.num_sets} sets`, ''],
        ].map(([k, v]) => (
          <span key={k} className="text-[11px] font-mono text-[#484f58]">
            {v ? <><span className="text-[#8b949e]">{v}</span> {k}</> : k}
          </span>
        ))}
      </div>
    </div>
  )
}
