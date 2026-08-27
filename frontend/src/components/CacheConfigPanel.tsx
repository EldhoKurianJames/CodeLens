import type { CacheConfig } from '../types'

interface Props {
  config: CacheConfig
  onChange: (c: CacheConfig) => void
  disabled?: boolean
}

const SIZES = [64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]
const BLOCKS = [8, 16, 32, 64, 128, 256, 512]
const ASSOCS = [1, 2, 4, 8, 16]

function numSets(c: CacheConfig) {
  const sets = c.size_bytes / (c.block_size_bytes * c.associativity)
  return sets >= 1 ? Math.floor(sets) : null
}

export default function CacheConfigPanel({ config, onChange, disabled }: Props) {
  const sets = numSets(config)
  const valid = sets !== null && sets >= 1

  function update(patch: Partial<CacheConfig>) {
    onChange({ ...config, ...patch })
  }

  const selectCls = `w-full rounded-lg bg-[#0d1117] ring-1 ring-white/[0.08] px-3 py-2 text-sm font-mono
    text-[#e6edf3] focus:ring-indigo-500/60 focus:outline-none transition-shadow
    disabled:opacity-40 disabled:cursor-not-allowed`

  return (
    <div className="rounded-2xl bg-[#161b22] ring-1 ring-white/[0.06] p-5 space-y-4">
      <p className="text-sm font-medium text-[#e6edf3]">Cache Configuration</p>

      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1.5">
          <label className="text-[11px] text-[#8b949e]">Cache size</label>
          <select value={config.size_bytes} disabled={disabled} onChange={e => update({ size_bytes: parseInt(e.target.value) })} className={selectCls}>
            {SIZES.map(s => <option key={s} value={s}>{s >= 1024 ? `${s/1024} KB` : `${s} B`}</option>)}
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-[11px] text-[#8b949e]">Block size</label>
          <select value={config.block_size_bytes} disabled={disabled} onChange={e => update({ block_size_bytes: parseInt(e.target.value) })} className={selectCls}>
            {BLOCKS.map(b => <option key={b} value={b}>{b} B</option>)}
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-[11px] text-[#8b949e]">Associativity</label>
          <select value={config.associativity} disabled={disabled} onChange={e => update({ associativity: parseInt(e.target.value) })} className={selectCls}>
            {ASSOCS.map(a => <option key={a} value={a}>{a}-way</option>)}
          </select>
        </div>
      </div>

      <div className="text-[11px] font-mono">
        {valid ? (
          <span className="text-[#484f58]">
            {sets} sets · {config.associativity} ways · {config.block_size_bytes} B/block
          </span>
        ) : (
          <span className="text-red-400/80">Invalid — size must be divisible by {config.block_size_bytes * config.associativity} B</span>
        )}
      </div>
    </div>
  )
}
