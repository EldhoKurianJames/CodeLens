import { useState } from 'react'
import { BookOpen, ChevronDown, ChevronUp } from 'lucide-react'

const SECTIONS = [
  {
    title: 'What is a cache?',
    body: 'A CPU cache is small, fast memory sitting between the CPU and main RAM. When data is needed, the CPU checks the cache first. If found (a "hit"), it skips the slow RAM access entirely.',
  },
  {
    title: 'Cache lines (blocks)',
    body: 'Data is loaded in fixed-size "cache lines" (e.g., 64 bytes). If you access one byte, the entire 64-byte line is pulled in — including nearby bytes. Good access patterns exploit this by reusing the whole line.',
  },
  {
    title: 'Hit rate vs. miss rate',
    body: 'Hit rate = fraction of accesses served by the cache. A 93% hit rate means 93% of reads avoided slow RAM. Miss rate is the complement. Even a 10% miss rate can halve performance if RAM latency is 100× cache latency.',
  },
  {
    title: 'Spatial locality',
    body: 'Accessing memory addresses close together (e.g., iterating an array sequentially) is efficient — each cache line load serves many consecutive accesses. Row-major matrix traversal exploits this.',
  },
  {
    title: 'Why column-major is slow',
    body: 'In row-major languages (C, Python, NumPy), a 2D array stores rows contiguously. Traversing column-by-column jumps by (row_size × element_size) bytes each step — often exceeding the entire cache, evicting every line before reuse.',
  },
  {
    title: 'Set associativity',
    body: 'A 2-way set-associative cache has groups ("sets") of 2 slots. A block can go into either slot in its set (decided by address modulo num_sets). More ways = fewer conflict misses, at the cost of complexity.',
  },
]

interface SectionProps {
  title: string
  body: string
}

function Section({ title, body }: SectionProps) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-b border-[#21262d] last:border-b-0">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm text-[#e6edf3] hover:bg-[#21262d] transition-colors"
      >
        <span className="font-medium">{title}</span>
        {open ? <ChevronUp size={14} className="text-[#8b949e] shrink-0" /> : <ChevronDown size={14} className="text-[#8b949e] shrink-0" />}
      </button>
      {open && (
        <p className="px-4 pb-4 text-xs text-[#8b949e] leading-relaxed animate-fade-in">
          {body}
        </p>
      )}
    </div>
  )
}

export default function EducationalSidebar() {
  const [visible, setVisible] = useState(false)

  return (
    <div className="rounded-2xl bg-[#161b22] ring-1 ring-white/[0.06] overflow-hidden">
      <button
        onClick={() => setVisible(v => !v)}
        className="flex w-full items-center gap-2.5 px-5 py-3.5 hover:bg-white/[0.02] transition-colors"
      >
        <div className="p-1 rounded-md bg-indigo-500/10">
          <BookOpen size={12} className="text-indigo-400" />
        </div>
        <span className="text-sm font-medium text-[#e6edf3] flex-1 text-left">
          Cache Concepts
        </span>
        {visible
          ? <ChevronUp size={14} className="text-[#8b949e]" />
          : <ChevronDown size={14} className="text-[#8b949e]" />}
      </button>
      {visible && (
        <div className="border-t border-[#30363d] animate-slide-up">
          {SECTIONS.map(s => <Section key={s.title} title={s.title} body={s.body} />)}
        </div>
      )}
    </div>
  )
}
