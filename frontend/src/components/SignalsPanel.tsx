import React, { useEffect, useState } from 'react'

const API_BASE = ''  // always use Vite proxy — supports both HTTP and HTTPS

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

// ── SignalCard ────────────────────────────────────────────────────────────────

function SignalCard({ sig }: { sig: CompositeSignal }) {
  const [expanded, setExpanded] = useState(false)
  const { sources } = sig
  const analyst  = sources.analyst_consensus
  const earnings = sources.earnings_surprise
  const alpaca   = sources.alpaca_news
  const yahoo    = sources.yahoo_news

  const congress = sources.congressional_trades

  const score   = sig.composite_score ?? 0
  const confPct = Math.round((sig.confidence ?? 0) * 100)

  // strip parenthetical suffix from verdict for badge
  const verdictLabel = (sig.verdict ?? '').replace(/ \(.*\)$/, '')
  const verdictColor  = score >= 0.15 ? 'bg-emerald-900 text-emerald-300 border border-emerald-700'
                      : score <= -0.15 ? 'bg-red-900 text-red-300 border border-red-700'
                      : 'bg-yellow-900 text-yellow-300 border border-yellow-700'

  const analystTotal = analyst.total ?? 0
  const bullPct  = analystTotal > 0 ? Math.round(((analyst.bull ?? 0) / analystTotal) * 100) : null
  const bearPct  = analystTotal > 0 ? Math.round(((analyst.bear ?? 0) / analystTotal) * 100) : null
  const holdPct  = analystTotal > 0 ? Math.round(((analyst.hold ?? 0) / analystTotal) * 100) : null

  return (
    <div className={`bg-gray-900 border-l-4 ${borderAccent(score)} border border-gray-700 rounded-xl overflow-hidden`}>

      {/* ── Top strip: symbol + score + confidence ── */}
      <div className="flex items-center justify-between px-4 pt-3 pb-2 bg-gray-800">
        <div className="flex items-center gap-3">
          <span className="text-white font-extrabold text-lg tracking-wide">{sig.symbol}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${verdictColor}`}>
            {verdictLabel}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <ConfRing pct={confPct} />
        </div>
      </div>

      {/* ── Composite score big number + gauge ── */}
      <div className="px-4 py-3 border-b border-gray-700">
        <div className="flex items-end justify-between mb-1.5">
          <div>
            <span className="text-xs text-gray-500 uppercase tracking-wide">Composite</span>
            <div className={`text-3xl font-black font-mono ${scoreColor(score)}`}>
              {score >= 0 ? '+' : ''}{score.toFixed(2)}
            </div>
          </div>
          <div className="text-right text-xs text-gray-500">
            <div>−1 bearish</div>
            <div>+1 bullish</div>
          </div>
        </div>
        <Gauge score={score} />
      </div>

      {/* ── Source rows ── */}
      <div className="px-4 py-3 space-y-3">

        {/* Analyst consensus */}
        <div>
          <div className="flex justify-between items-center mb-1">
            <span className="text-xs text-gray-400 font-semibold">Analyst Consensus</span>
            <span className="text-xs text-gray-600">wt 40%</span>
          </div>
          <div className="flex items-center gap-2 mb-1">
            <Gauge score={analyst.score ?? null} />
            <span className={`text-sm font-bold font-mono ${scoreColor(analyst.score ?? null)}`}>
              {fmt(analyst.score, 2, true)}
            </span>
          </div>
          {analystTotal > 0 && (
            <div className="flex gap-1 text-xs">
              {/* buy bar */}
              <div
                className="h-5 bg-emerald-600 rounded flex items-center justify-center text-white font-bold text-xs px-1"
                style={{ width: `${bullPct}%`, minWidth: 28 }}
              >
                {analyst.bull}▲
              </div>
              {/* hold bar */}
              <div
                className="h-5 bg-gray-600 rounded flex items-center justify-center text-gray-200 font-bold text-xs px-1"
                style={{ width: `${holdPct}%`, minWidth: 28 }}
              >
                {analyst.hold}–
              </div>
              {/* sell bar */}
              <div
                className="h-5 bg-red-700 rounded flex items-center justify-center text-white font-bold text-xs px-1"
                style={{ width: `${bearPct}%`, minWidth: 28 }}
              >
                {analyst.bear}▼
              </div>
            </div>
          )}
          {analyst.price_target != null && (
            <div className="mt-1 text-xs">
              <span className="text-gray-500">Price target: </span>
              <span className="text-blue-400 font-bold font-mono">${analyst.price_target.toFixed(2)}</span>
            </div>
          )}
        </div>

        {/* Earnings surprise */}
        <div>
          <div className="flex justify-between items-center mb-1">
            <span className="text-xs text-gray-400 font-semibold">Earnings Surprise</span>
            <span className="text-xs text-gray-600">wt 25%</span>
          </div>
          <div className="flex items-center gap-2 mb-1">
            <Gauge score={earnings.score ?? null} />
            <span className={`text-sm font-bold font-mono ${scoreColor(earnings.score ?? null)}`}>
              {fmt(earnings.score, 2, true)}
            </span>
          </div>
          {earnings.surprise_pct != null && (
            <div className={`text-xs font-semibold ${earnings.surprise_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              EPS beat/miss: {earnings.surprise_pct >= 0 ? '+' : ''}{earnings.surprise_pct.toFixed(2)}%
            </div>
          )}
        </div>

        {/* News scores side by side */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-gray-400 font-semibold">Alpaca News</span>
              <span className="text-xs text-gray-600">wt 18%</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className={`text-lg font-black font-mono ${scoreColor(alpaca.score ?? null)}`}>
                {fmt(alpaca.score, 2, true)}
              </span>
            </div>
            <div className="text-xs text-gray-600">{alpaca.articles ?? 0} articles</div>
          </div>
          <div>
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-gray-400 font-semibold">Yahoo News</span>
              <span className="text-xs text-gray-600">wt 12%</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className={`text-lg font-black font-mono ${scoreColor(yahoo.score ?? null)}`}>
                {fmt(yahoo.score, 2, true)}
              </span>
            </div>
            <div className="text-xs text-gray-600">{yahoo.articles ?? 0} articles</div>
          </div>
        </div>

        {/* Congressional / Insider trades */}
        <div className="border-t border-gray-800 pt-3">
          <div className="flex justify-between items-center mb-1">
            <span className="text-xs text-gray-400 font-semibold">Congressional Trades</span>
            <span className="text-xs text-gray-600">wt 13% · SEC EDGAR 90d</span>
          </div>
          {congress.score != null ? (
            <div className="flex items-center gap-3">
              <span className={`text-lg font-black font-mono ${scoreColor(congress.score)}`}>
                {fmt(congress.score, 2, true)}
              </span>
              <div className="flex gap-1.5 text-xs">
                {(congress.congress_buys ?? 0) > 0 && (
                  <span className="px-1.5 py-0.5 bg-emerald-900 text-emerald-300 rounded font-bold">
                    {congress.congress_buys} BUY
                  </span>
                )}
                {(congress.congress_sells ?? 0) > 0 && (
                  <span className="px-1.5 py-0.5 bg-red-900 text-red-300 rounded font-bold">
                    {congress.congress_sells} SELL
                  </span>
                )}
                {(congress.total_filings ?? 0) > 0 && (
                  <span className="px-1.5 py-0.5 bg-gray-800 text-gray-400 rounded">
                    {congress.total_filings} Form4
                  </span>
                )}
              </div>
            </div>
          ) : (
            <div className="text-xs text-gray-600">
              {(congress.total_filings ?? 0) > 0
                ? `${congress.total_filings} Form 4 filings — direction unclear`
                : 'No filings in past 90 days'}
            </div>
          )}
        </div>
      </div>

      {/* ── Headlines toggle ── */}
      {(sig.yahoo_news_headlines ?? []).length > 0 && (
        <div className="border-t border-gray-700">
          <button
            onClick={() => setExpanded(e => !e)}
            className="w-full text-left px-4 py-2 text-xs text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors flex justify-between"
          >
            <span>Headlines ({sig.yahoo_news_headlines.length})</span>
            <span>{expanded ? '▲' : '▼'}</span>
          </button>
          {expanded && (
            <div className="px-4 pb-3 space-y-1.5">
              {(sig.yahoo_news_headlines ?? []).map((h, i) => (
                <div key={i} className="text-xs text-gray-400 leading-snug border-l-2 border-gray-700 pl-2">
                  {h}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── SignalsPanel ──────────────────────────────────────────────────────────────

export default function SignalsPanel() {
  const [signals, setSignals]       = useState<Record<string, CompositeSignal>>({})
  const [loading, setLoading]       = useState(true)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [error, setError]           = useState<string | null>(null)

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

  const sorted = Object.values(signals).sort(
    (a, b) => (b.composite_score ?? 0) - (a.composite_score ?? 0)
  )

  // Summary stats
  const bullish = sorted.filter(s => s.composite_score >= 0.15).length
  const bearish = sorted.filter(s => s.composite_score <= -0.15).length
  const neutral = sorted.length - bullish - bearish
  const avgScore = sorted.length
    ? sorted.reduce((s, x) => s + x.composite_score, 0) / sorted.length
    : null

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

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-white font-bold text-base">Multi-Source Signal Board</h2>
          <p className="text-xs text-gray-500">Analyst 35% · Earnings 22% · Alpaca News 18% · Yahoo 12% · Congress 13%</p>
        </div>
        <div className="flex items-center gap-3">
          {/* market mood pills */}
          <div className="flex gap-1.5 text-xs font-semibold">
            <span className="px-2 py-1 bg-emerald-900 text-emerald-300 rounded-full">{bullish} Bull</span>
            <span className="px-2 py-1 bg-yellow-900 text-yellow-300 rounded-full">{neutral} Neutral</span>
            <span className="px-2 py-1 bg-red-900 text-red-300 rounded-full">{bearish} Bear</span>
          </div>
          {avgScore !== null && (
            <div className="text-xs">
              <span className="text-gray-500">Avg: </span>
              <span className={`font-bold font-mono ${scoreColor(avgScore)}`}>
                {avgScore >= 0 ? '+' : ''}{avgScore.toFixed(2)}
              </span>
            </div>
          )}
          {lastUpdated && (
            <span className="text-xs text-gray-600">{lastUpdated}</span>
          )}
          <button
            onClick={fetchSignals}
            className="text-xs px-3 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors"
          >
            ↻
          </button>
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-gray-500 bg-gray-900 rounded-xl">
          No signal data — start the trading loop first.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          {sorted.map(sig => <SignalCard key={sig.symbol} sig={sig} />)}
        </div>
      )}
    </div>
  )
}
