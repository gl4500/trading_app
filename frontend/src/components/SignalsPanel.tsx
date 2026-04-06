import React, { useEffect, useState, Component, ErrorInfo, ReactNode } from 'react'

const API_BASE = ''  // always use Vite proxy — supports both HTTP and HTTPS

// ── Error boundary ────────────────────────────────────────────────────────────

interface EBState { error: Error | null }
class SignalErrorBoundary extends Component<{ children: ReactNode }, EBState> {
  state: EBState = { error: null }
  static getDerivedStateFromError(e: Error): EBState { return { error: e } }
  componentDidCatch(e: Error, info: ErrorInfo) {
    console.error('[SignalsPanel] render crash:', e, info.componentStack)
  }
  render() {
    if (this.state.error) {
      return (
        <div className="p-6 bg-red-950 border border-red-700 rounded-xl text-red-300 space-y-2">
          <div className="font-bold text-red-400">Signals panel crashed during render</div>
          <div className="font-mono text-xs whitespace-pre-wrap break-all">
            {this.state.error.message}
          </div>
          <div className="font-mono text-xs text-red-500 whitespace-pre-wrap break-all">
            {this.state.error.stack}
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

interface SourceDetail {
  score: number | null
  weight: number
  bull?: number
  hold?: number
  bear?: number
  total?: number
  price_target?: number | null
  surprise_pct?: number | null
  articles?: number
  congress_buys?: number
  congress_sells?: number
  congress_total?: number
  total_filings?: number
  window_days?: number
}

interface CompositeSignal {
  symbol: string
  composite_score: number
  confidence: number
  verdict: string
  sources: {
    analyst_consensus: SourceDetail
    earnings_surprise: SourceDetail
    alpaca_news: SourceDetail
    yahoo_news: SourceDetail
    congressional_trades: SourceDetail
  }
  yahoo_news_headlines: string[]
}

// ── helpers ──────────────────────────────────────────────────────────────────

function scoreColor(s: number | null): string {
  if (s === null) return 'text-gray-500'
  if (s >= 0.4)  return 'text-emerald-400'
  if (s >= 0.15) return 'text-green-400'
  if (s <= -0.4) return 'text-red-500'
  if (s <= -0.15)return 'text-red-400'
  return 'text-yellow-400'
}

function scoreBg(s: number | null): string {
  if (s === null) return 'bg-gray-700'
  if (s >= 0.4)  return 'bg-emerald-500'
  if (s >= 0.15) return 'bg-green-500'
  if (s <= -0.4) return 'bg-red-600'
  if (s <= -0.15)return 'bg-red-500'
  return 'bg-yellow-500'
}

function borderAccent(s: number): string {
  if (s >= 0.4)  return 'border-emerald-500'
  if (s >= 0.15) return 'border-green-600'
  if (s <= -0.4) return 'border-red-600'
  if (s <= -0.15)return 'border-red-700'
  return 'border-yellow-600'
}

function fmt(n: number | null | undefined, decimals = 2, sign = false): string {
  if (n == null) return '—'
  const s = n.toFixed(decimals)
  return sign && n > 0 ? `+${s}` : s
}

// Horizontal gauge: maps score [-1,+1] to a coloured fill bar with centre marker
function Gauge({ score }: { score: number | null }) {
  if (score === null) return <div className="text-gray-600 text-xs">no data</div>
  const pct = ((score + 1) / 2) * 100          // 0–100
  const clampedPct = Math.max(2, Math.min(98, pct))
  const bg = scoreBg(score)
  return (
    <div className="relative h-3 bg-gray-700 rounded-full overflow-hidden">
      {/* centre zero line */}
      <div className="absolute inset-y-0 left-1/2 w-px bg-gray-500 z-10" />
      {/* fill from centre */}
      {score >= 0 ? (
        <div
          className={`absolute inset-y-0 ${bg} opacity-80`}
          style={{ left: '50%', width: `${clampedPct - 50}%` }}
        />
      ) : (
        <div
          className={`absolute inset-y-0 ${bg} opacity-80`}
          style={{ right: `${50}%`, width: `${50 - clampedPct}%` }}
        />
      )}
    </div>
  )
}

// Donut-style confidence ring (CSS only)
function ConfRing({ pct }: { pct: number }) {
  const color = pct >= 70 ? '#10b981' : pct >= 40 ? '#f59e0b' : '#ef4444'
  const r = 14, circ = 2 * Math.PI * r
  const dash = (pct / 100) * circ
  return (
    <svg width="36" height="36" viewBox="0 0 36 36">
      <circle cx="18" cy="18" r={r} fill="none" stroke="#374151" strokeWidth="4" />
      <circle
        cx="18" cy="18" r={r} fill="none"
        stroke={color} strokeWidth="4"
        strokeDasharray={`${dash} ${circ}`}
        strokeLinecap="round"
        transform="rotate(-90 18 18)"
      />
      <text x="18" y="22" textAnchor="middle" fontSize="9" fill={color} fontWeight="bold">
        {pct}%
      </text>
    </svg>
  )
}

// ── SignalRow ─────────────────────────────────────────────────────────────────

function SignalRow({ sig }: { sig: CompositeSignal }) {
  const [expanded, setExpanded] = useState(false)
  const sources  = sig.sources ?? ({} as CompositeSignal['sources'])
  const analyst  = sources.analyst_consensus    ?? ({} as SourceDetail)
  const earnings = sources.earnings_surprise    ?? ({} as SourceDetail)
  const alpaca   = sources.alpaca_news          ?? ({} as SourceDetail)
  const yahoo    = sources.yahoo_news           ?? ({} as SourceDetail)
  const congress = sources.congressional_trades ?? ({} as SourceDetail)

  const score   = sig.composite_score ?? 0
  const confPct = Math.round((sig.confidence ?? 0) * 100)

  const verdictLabel = (sig.verdict ?? '').replace(/ \(.*\)$/, '')
  const verdictColor = score >= 0.15  ? 'bg-emerald-900 text-emerald-300 border border-emerald-700'
                     : score <= -0.15 ? 'bg-red-900 text-red-300 border border-red-700'
                     : 'bg-yellow-900 text-yellow-300 border border-yellow-700'

  const analystTotal = analyst.total ?? 0

  return (
    <>
      <tr className={`border-b border-gray-800 hover:bg-gray-800/30 transition-colors border-l-4 ${borderAccent(score)}`}>

        {/* Symbol + verdict */}
        <td className="px-3 py-2.5 whitespace-nowrap">
          <div className="font-extrabold text-white text-sm tracking-wide">{sig.symbol}</div>
          <span className={`text-xs px-1.5 py-0.5 rounded-full font-semibold ${verdictColor}`}>
            {verdictLabel}
          </span>
        </td>

        {/* Composite score + gauge */}
        <td className="px-3 py-2.5 w-36">
          <div className={`text-xl font-black font-mono ${scoreColor(score)} leading-tight mb-1`}>
            {score >= 0 ? '+' : ''}{score.toFixed(2)}
          </div>
          <Gauge score={score} />
        </td>

        {/* Confidence ring */}
        <td className="px-3 py-2.5 text-center">
          <ConfRing pct={confPct} />
        </td>

        {/* Analyst consensus */}
        <td className="px-3 py-2.5 w-44">
          <div className={`text-sm font-bold font-mono ${scoreColor(analyst.score ?? null)} mb-1`}>
            {fmt(analyst.score, 2, true)}
          </div>
          <Gauge score={analyst.score ?? null} />
          {analystTotal > 0 && (
            <div className="flex gap-0.5 mt-1.5">
              <span className="px-1.5 py-0.5 bg-emerald-900 text-emerald-300 text-xs rounded font-bold">
                {analyst.bull}▲
              </span>
              <span className="px-1.5 py-0.5 bg-gray-700 text-gray-300 text-xs rounded font-bold">
                {analyst.hold}–
              </span>
              <span className="px-1.5 py-0.5 bg-red-900 text-red-300 text-xs rounded font-bold">
                {analyst.bear}▼
              </span>
            </div>
          )}
          {analyst.price_target != null && (
            <div className="text-xs text-blue-400 font-mono mt-0.5">
              PT ${analyst.price_target.toFixed(0)}
            </div>
          )}
        </td>

        {/* Earnings surprise */}
        <td className="px-3 py-2.5 w-32">
          <div className={`text-sm font-bold font-mono ${scoreColor(earnings.score ?? null)} mb-1`}>
            {fmt(earnings.score, 2, true)}
          </div>
          <Gauge score={earnings.score ?? null} />
          {earnings.surprise_pct != null && (
            <div className={`text-xs font-semibold mt-1 ${earnings.surprise_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {earnings.surprise_pct >= 0 ? '+' : ''}{earnings.surprise_pct.toFixed(1)}% EPS
            </div>
          )}
        </td>

        {/* Alpaca news */}
        <td className="px-3 py-2.5 w-24">
          <div className={`text-sm font-bold font-mono ${scoreColor(alpaca.score ?? null)}`}>
            {fmt(alpaca.score, 2, true)}
          </div>
          <div className="text-xs text-gray-600 mt-0.5">{alpaca.articles ?? 0} art.</div>
        </td>

        {/* Yahoo news */}
        <td className="px-3 py-2.5 w-24">
          <div className={`text-sm font-bold font-mono ${scoreColor(yahoo.score ?? null)}`}>
            {fmt(yahoo.score, 2, true)}
          </div>
          <div className="text-xs text-gray-600 mt-0.5">{yahoo.articles ?? 0} art.</div>
        </td>

        {/* Congressional trades */}
        <td className="px-3 py-2.5 w-32">
          {congress.score != null ? (
            <>
              <div className={`text-sm font-bold font-mono ${scoreColor(congress.score)} mb-0.5`}>
                {fmt(congress.score, 2, true)}
              </div>
              <div className="flex flex-wrap gap-0.5">
                {(congress.congress_buys ?? 0) > 0 && (
                  <span className="px-1.5 py-0.5 bg-emerald-900 text-emerald-300 text-xs rounded font-bold">
                    {congress.congress_buys} BUY
                  </span>
                )}
                {(congress.congress_sells ?? 0) > 0 && (
                  <span className="px-1.5 py-0.5 bg-red-900 text-red-300 text-xs rounded font-bold">
                    {congress.congress_sells} SELL
                  </span>
                )}
                {(congress.total_filings ?? 0) > 0 && (
                  <span className="px-1.5 py-0.5 bg-gray-800 text-gray-400 text-xs rounded">
                    {congress.total_filings} Form4
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="text-xs text-gray-600">
              {(congress.total_filings ?? 0) > 0
                ? `${congress.total_filings} filings`
                : '—'}
            </div>
          )}
        </td>

        {/* Headlines toggle */}
        <td className="px-3 py-2.5 text-center whitespace-nowrap">
          {(sig.yahoo_news_headlines ?? []).length > 0 ? (
            <button
              onClick={() => setExpanded(e => !e)}
              className="text-xs px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200 rounded transition-colors"
            >
              {expanded ? '▲' : '▼'} {sig.yahoo_news_headlines.length}
            </button>
          ) : (
            <span className="text-xs text-gray-700">—</span>
          )}
        </td>
      </tr>

      {/* Expanded headlines row */}
      {expanded && (
        <tr className="bg-gray-900/60">
          <td colSpan={9} className="px-5 py-2.5 border-b border-gray-800">
            <div className="space-y-1">
              {(sig.yahoo_news_headlines ?? []).map((h, i) => (
                <div key={i} className="text-xs text-gray-400 leading-snug border-l-2 border-gray-700 pl-2">
                  {h}
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ── SignalsPanel ──────────────────────────────────────────────────────────────

type SortCol = 'composite' | 'confidence' | 'analyst' | 'earnings' | 'alpaca' | 'yahoo' | 'congress'
type VerdictFilter = 'all' | 'bull' | 'neutral' | 'bear'

function colScore(sig: CompositeSignal, col: SortCol): number {
  const s = sig.sources ?? ({} as CompositeSignal['sources'])
  switch (col) {
    case 'composite':  return sig.composite_score ?? 0
    case 'confidence': return sig.confidence ?? 0
    case 'analyst':    return s.analyst_consensus?.score   ?? -9
    case 'earnings':   return s.earnings_surprise?.score   ?? -9
    case 'alpaca':     return s.alpaca_news?.score         ?? -9
    case 'yahoo':      return s.yahoo_news?.score          ?? -9
    case 'congress':   return s.congressional_trades?.score ?? -9
  }
}

function SortTh({
  col, label, sub, center,
  current, dir,
  onSort,
}: {
  col: SortCol; label: string; sub?: string; center?: boolean
  current: SortCol; dir: 'asc' | 'desc'
  onSort: (c: SortCol) => void
}) {
  const active = current === col
  return (
    <th
      onClick={() => onSort(col)}
      className={`px-3 py-2 cursor-pointer select-none group hover:bg-gray-700 transition-colors ${center ? 'text-center' : 'text-left'}`}
    >
      <div className={`flex items-center gap-1 text-xs font-semibold uppercase tracking-wide ${active ? 'text-blue-400' : 'text-gray-400 group-hover:text-gray-200'} ${center ? 'justify-center' : ''}`}>
        {label}
        {sub && <span className="text-gray-600 normal-case font-normal">{sub}</span>}
        <span className={`text-xs ${active ? 'text-blue-400' : 'text-gray-700 group-hover:text-gray-500'}`}>
          {active ? (dir === 'desc' ? '▼' : '▲') : '⇅'}
        </span>
      </div>
    </th>
  )
}

export default function SignalsPanel() {
  const [signals, setSignals]         = useState<Record<string, CompositeSignal>>({})
  const [loading, setLoading]         = useState(true)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [error, setError]             = useState<string | null>(null)
  const [sortCol, setSortCol]         = useState<SortCol>('composite')
  const [sortDir, setSortDir]         = useState<'desc' | 'asc'>('desc')
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>('all')
  const [symbolSearch, setSymbolSearch]   = useState('')

  const fetchSignals = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/signals`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSignals(data.signals ?? {})
      setLastUpdated(new Date().toLocaleTimeString())
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSignals()
    const interval = setInterval(fetchSignals, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  const handleSort = (col: SortCol) => {
    if (col === sortCol) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortCol(col); setSortDir('desc') }
  }

  const allSignals = Object.values(signals)

  // Summary counts (always over full set)
  const bullish = allSignals.filter(s => (s.composite_score ?? 0) >= 0.15).length
  const bearish = allSignals.filter(s => (s.composite_score ?? 0) <= -0.15).length
  const neutral = allSignals.length - bullish - bearish
  const avgScore = allSignals.length
    ? allSignals.reduce((s, x) => s + (x.composite_score ?? 0), 0) / allSignals.length
    : null

  // Filter then sort
  const filtered = allSignals.filter(sig => {
    if (symbolSearch && !sig.symbol.includes(symbolSearch.toUpperCase())) return false
    const sc = sig.composite_score ?? 0
    if (verdictFilter === 'bull')    return sc >= 0.15
    if (verdictFilter === 'bear')    return sc <= -0.15
    if (verdictFilter === 'neutral') return sc > -0.15 && sc < 0.15
    return true
  })
  const sorted = [...filtered].sort((a, b) => {
    const diff = colScore(b, sortCol) - colScore(a, sortCol)
    return sortDir === 'desc' ? diff : -diff
  })

  if (loading) return (
    <div className="flex items-center justify-center h-48 text-gray-500">
      Loading composite signals…
    </div>
  )

  if (error) return (
    <div className="flex items-center justify-center h-48 text-red-400">
      Failed to load signals: {error}
    </div>
  )

  const pillBase = 'px-2.5 py-1 rounded-full text-xs font-semibold transition-colors cursor-pointer border'
  const verdictPill = (v: VerdictFilter, active: string, inactive: string) =>
    verdictFilter === v ? active : inactive

  return (
    <SignalErrorBoundary>
    <div className="space-y-3">

      {/* ── Header ── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-white font-bold text-base">Multi-Source Signal Board</h2>
          <p className="text-xs text-gray-500">Analyst 35% · Earnings 22% · Alpaca News 18% · Yahoo 12% · Congress 13%</p>
        </div>
        <div className="flex items-center gap-3">
          {avgScore !== null && (
            <div className="text-xs">
              <span className="text-gray-500">Avg: </span>
              <span className={`font-bold font-mono ${scoreColor(avgScore)}`}>
                {avgScore >= 0 ? '+' : ''}{avgScore.toFixed(2)}
              </span>
            </div>
          )}
          {lastUpdated && <span className="text-xs text-gray-600">{lastUpdated}</span>}
          <button
            onClick={fetchSignals}
            className="text-xs px-3 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors"
          >↻</button>
        </div>
      </div>

      {/* ── Verdict filter pills ── */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-gray-600 mr-1">Filter:</span>
        <button
          onClick={() => setVerdictFilter('all')}
          className={`${pillBase} ${verdictPill('all',
            'bg-gray-600 text-white border-gray-500',
            'bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-500 hover:text-gray-200')}`}
        >All ({allSignals.length})</button>
        <button
          onClick={() => setVerdictFilter('bull')}
          className={`${pillBase} ${verdictPill('bull',
            'bg-emerald-600 text-white border-emerald-500',
            'bg-emerald-950 text-emerald-400 border-emerald-800 hover:border-emerald-600 hover:text-emerald-200')}`}
        >▲ Bullish ({bullish})</button>
        <button
          onClick={() => setVerdictFilter('neutral')}
          className={`${pillBase} ${verdictPill('neutral',
            'bg-yellow-600 text-white border-yellow-500',
            'bg-yellow-950 text-yellow-400 border-yellow-800 hover:border-yellow-600 hover:text-yellow-200')}`}
        >– Neutral ({neutral})</button>
        <button
          onClick={() => setVerdictFilter('bear')}
          className={`${pillBase} ${verdictPill('bear',
            'bg-red-600 text-white border-red-500',
            'bg-red-950 text-red-400 border-red-800 hover:border-red-600 hover:text-red-200')}`}
        >▼ Bearish ({bearish})</button>
        {(verdictFilter !== 'all' || symbolSearch) && (
          <span className="text-xs text-gray-500 ml-1">
            Showing {sorted.length} of {allSignals.length}
          </span>
        )}
      </div>

      {sorted.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-gray-500 bg-gray-900 rounded-xl">
          {allSignals.length === 0
            ? 'No signal data — start the trading loop first.'
            : `No ${verdictFilter} signals right now.`}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-700">
          <table className="w-full text-sm min-w-[860px] border-collapse">
            <thead>
              <tr className="bg-gray-800 border-b border-gray-700">
                {/* Symbol — text search filter */}
                <th className="px-3 py-2 text-left bg-gray-800">
                  <div className="text-xs text-gray-400 font-semibold uppercase tracking-wide mb-1">Symbol</div>
                  <input
                    type="text"
                    value={symbolSearch}
                    onChange={e => setSymbolSearch(e.target.value)}
                    placeholder="Filter…"
                    className="w-20 px-2 py-0.5 bg-gray-700 border border-gray-600 rounded text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                  />
                </th>
                <SortTh col="composite"  label="Composite"                    current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortTh col="confidence" label="Conf."        center          current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortTh col="analyst"    label="Analyst"   sub=" 35%"         current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortTh col="earnings"   label="Earnings"  sub=" 22%"         current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortTh col="alpaca"     label="Alpaca"    sub=" 18%"         current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortTh col="yahoo"      label="Yahoo"     sub=" 12%"         current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortTh col="congress"   label="Congress"  sub=" 13%"         current={sortCol} dir={sortDir} onSort={handleSort} />
                <th className="px-3 py-2 text-center text-xs text-gray-400 font-semibold uppercase tracking-wide">Headlines</th>
              </tr>
            </thead>
            <tbody className="bg-gray-900 divide-y divide-gray-800/50">
              {sorted.map(sig => <SignalRow key={sig.symbol} sig={sig} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
    </SignalErrorBoundary>
  )
}
