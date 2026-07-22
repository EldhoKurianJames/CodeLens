import { useMemo } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import type { AccessLogEntry } from '../types'

interface Props {
  accessLog: AccessLogEntry[]
  finalHitRate?: number
}

interface DataPoint {
  access: number
  hitRate: number
}

export default function HitRateChart({ accessLog, finalHitRate }: Props) {
  const data = useMemo<DataPoint[]>(() => {
    let hits = 0
    return accessLog.map((entry, i) => {
      if (entry.hit) hits++
      return { access: i + 1, hitRate: parseFloat(((hits / (i + 1)) * 100).toFixed(2)) }
    })
  }, [accessLog])

  if (data.length === 0) return null

  return (
    <div className="rounded-2xl bg-[#161b22] ring-1 ring-white/[0.06] p-5">
      <p className="text-sm font-medium text-[#e6edf3] mb-4">
        Cumulative Hit Rate
      </p>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
          <defs>
            <linearGradient id="hitRateGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
          <XAxis
            dataKey="access"
            stroke="#484f58"
            tick={{ fill: '#8b949e', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }}
            tickLine={false}
            label={{ value: 'Access #', position: 'insideBottomRight', offset: -4, fill: '#484f58', fontSize: 10 }}
          />
          <YAxis
            domain={[0, 100]}
            stroke="#484f58"
            tick={{ fill: '#8b949e', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }}
            tickLine={false}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            contentStyle={{ background: '#21262d', border: '1px solid #30363d', borderRadius: '8px', fontSize: '12px' }}
            labelStyle={{ color: '#8b949e' }}
            itemStyle={{ color: '#6366f1' }}
            formatter={(v: number) => [`${v.toFixed(1)}%`, 'Hit Rate']}
            labelFormatter={(l: number) => `Access #${l}`}
          />
          {finalHitRate !== undefined && (
            <ReferenceLine
              y={finalHitRate * 100}
              stroke="#22c55e"
              strokeDasharray="4 2"
              label={{ value: `${(finalHitRate * 100).toFixed(1)}%`, fill: '#22c55e', fontSize: 10, position: 'right' }}
            />
          )}
          <Area
            type="monotone"
            dataKey="hitRate"
            stroke="#6366f1"
            strokeWidth={2}
            fill="url(#hitRateGrad)"
            dot={false}
            activeDot={{ r: 4, fill: '#6366f1', stroke: '#161b22', strokeWidth: 2 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
