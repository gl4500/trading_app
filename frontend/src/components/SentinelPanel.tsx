import React, { useEffect, useState } from 'react'

const API_BASE = ''

interface Catalyst {
  headline: string
  summary?: string
  symbol?: string
  score: number
  category: string
  sectors?: string[]
  reason?: string
  source?: string
  date?: string
  detected_at: string
}

interface SentinelData {
  market_status: string
  market_is_open: boolean
  minutes_until_open: number
  last_poll: string | null
  catalyst_count: number
  catalysts: Catalyst[]
}

interface PriceSnap {
  symbol: string
  headline: string
  score: number
  category: string
  price_at: number
  detected_at: string
  price_open: number | null
  price_1h: number | null
  change_open: number | null
  change_1h: number | null
}

interface ImpactData {
  total: number
  confirmed: PriceSnap[]
  pending: PriceSnap[]
}

// ── helpers ──────────────────────────────────────────────────────────────────

function categoryColor(cat: string): string {
  switch (cat) {
    case 'policy':       return 'bg-purple-900 text-purple-300 border-purple-700'
    case 'macro':        return 'bg-blue-900 text-blue-300 border-blue-700'
    case 'geopolitical': return 'bg-orange-900 text-orange-300 border-orange-700'
    case 'regulatory':   return 'bg-pink-900 text-pink-300 border-pink-700'
    default:             return 'bg-amber-900 text-amber-300 border-amber-700'
  }
}

function categoryBorder(cat: string): string {
  switch (cat) {
    case 'policy':       return 'border-purple-600'
    case 'macro':        return 'border-blue-600'
    case 'geopolitical': return 'border-orange-600'
    case 'regulatory':   return 'border-pink-600'
    default:             return 'border-amber-600'
  }
}

function scoreBar(score: number): string {
  if (score >= 4) return 'bg-red-500'
  if (score >= 3) return 'bg-orange-500'
  if (score >= 2) return 'bg-yellow-500'
  return 'bg-gray-600'
}

function changePill(pct: number | null): JSX.Element {
  if (pct === null) return <span className="text-gray-600 text-xs">pending</span>
  const cls = pct > 0 ? 'text-emerald-400' : pct < 0 ? 'text-red-400' : 'text-gray-400'
  return <span className={`text-xs font-bold font-mono ${cls}`}>{pct > 0 ? '+' : ''}{pct.toFixed(2)}%</span>
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
  catch { return '—' }
}

function minsToHM(mins: number): string {
  if (mins <= 0) return 'now'
  const h = Math.floor(mins / 60)
  const m = Math.round(mins % 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

// ── CatalystCard ──────────────────────────────────────────────────────────────

function CatalystCard({ cat }: { cat: Catalyst }) {
  return (
    <div className={`bg-gray-900 border border-gray-700 border-l-4 ${categoryBorder(cat.category)} rounded-lg p-3 space-y-1.5`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          {cat.symbol && (
            <span className="text-white font-bold text-sm">{cat.symbol}</span>
          )}
          <span className={`text-xs px-1.5 py-0.5 rounded border ${categoryColor(cat.category)} font-semibold`}>
            {cat.category.toUpperCase()}
          </span>
          {/* score dots */}
          <div className="flex gap-0.5">
            {Array.from({ length: Math.min(cat.score, 6) }).map((_, i) => (
              <div key={i} className={`w-2 h-2 rounded-full ${scoreBar(cat.score)}`} />
            ))}
          </div>
        </div>
        <span className="text-xs text-gray-600 whitespace-nowrap">{fmtTime(cat.detected_at)}</span>
      </div>

      <p className="text-sm text-gray-200 leading-snug">{cat.headline}</p>

      {cat.summary && (
        <p className="text-xs text-gray-500 leading-snug line-clamp-2">{cat.summary}</p>
      )}

      <div className="flex items-center gap-3 flex-wrap">
        {cat.sectors && cat.sectors.length > 0 && (
          <div className="flex gap-1 flex-wrap">
            {cat.sectors.map(s => (
              <span key={s} className="text-xs px-1.5 py-0.5 bg-gray-800 text-gray-400 rounded">
                {s}
              </span>
            ))}
          </div>
        )}
        {cat.reason && (
          <span className="text-xs text-gray-600 italic">{cat.reason}</span>
        )}
      </div>
    </div>
  )
}

// ── ImpactRow ─────────────────────────────────────────────────────────────────

function ImpactRow({ snap }: { snap: PriceSnap }) {
  const confirmed = snap.change_1h !== null
  return (
    <div className="grid grid-cols-12 gap-2 items-center py-2 border-b border-gray-800 text-sm">
      <div className="col-span-1 font-bold text-white">{snap.symbol}</div>
      <div className="col-span-4 text-gray-400 text-xs truncate" title={snap.headline}>{snap.headline}</div>
      <div className="col-span-1 text-center">
        <span className={`text-xs px-1 py-0.5 rounded ${categoryColor(snap.category)}`}>
          {snap.category.slice(0, 3).toUpperCase()}
        </span>
      </div>
      <div className="col-span-1 text-center font-mono text-gray-400 text-xs">
        ${snap.price_at.toFixed(2)}
      </div>
      <div className="col-span-2 text-center">
        <div className="text-xs text-gray-500">At open</div>
        {changePill(snap.change_open)}
      </div>
      <div className="col-span-2 text-center">
        <div className="text-xs text-gray-500">Sustained</div>
        {changePill(snap.change_1h)}
      </div>
      <div className="col-span-1 text-center">
        {confirmed
          ? <span className="text-xs text-emerald-500">✓</span>
          : <span className="text-xs text-yellow-600">…</span>}
      </div>
    </div>
  )
}

// ── SentinelPanel ─────────────────────────────────────────────────────────────

export default function SentinelPanel() {
  const [sentinel, setSentinel]   = useState<SentinelData | null>(null)
  const [impact, setImpact]       = useState<ImpactData | null>(null)
  const [loading, setLoading]     = useState(true)
  const [lastUpdated, setLU]      = useState<string | null>(null)
  const [activeView, setView]     = useState<'feed' | 'impact'>('feed')

  const fetchAll = async () => {
    try {
      const [sRes, iRes] = await Promise.all([
        fetch(`${API_BASE}/api/sentinel`),
        fetch(`${API_BASE}/api/news-impact`),
      ])
      if (sRes.ok) setSentinel(await sRes.json())
      if (iRes.ok) setImpact(await iRes.json())
      setLU(new Date().toLocaleTimeString())
    } catch (_) {}
    finally { setLoading(false) }
  }

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 60_000)
    return () => clearInterval(interval)
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center h-48 text-gray-500">
      Loading sentinel data…
    </div>
  )

  const catalysts = sentinel?.catalysts ?? []
  const byCategory = catalysts.reduce<Record<string, Catalyst[]>>((acc, c) => {
    const k = c.category || 'catalyst';
    (acc[k] = acc[k] || []).push(c)
    return acc
  }, {})

  const categoryOrder = ['policy', 'macro', 'geopolitical', 'regulatory', 'catalyst']
  const sortedCategories = [
    ...categoryOrder.filter(k => byCategory[k]),
    ...Object.keys(byCategory).filter(k => !categoryOrder.includes(k)),
  ]

  return (
    <div className="space-y-4">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-white font-bold text-base">Overnight Sentinel</h2>
          <p className="text-xs text-gray-500">
            News · Policy · Earnings · Macro · Geopolitical — after-hours intelligence
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && <span className="text-xs text-gray-600">{lastUpdated}</span>}
          <button onClick={fetchAll} className="text-xs px-3 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg">↻ Refresh</button>
        </div>
      </div>

      {/* ── Status bar ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-gray-900 rounded-xl p-3 border border-gray-700">
          <div className="text-xs text-gray-500 mb-1">Market</div>
          <div className={`text-sm font-bold ${sentinel?.market_is_open ? 'text-emerald-400' : 'text-red-400'}`}>
            {sentinel?.market_status?.toUpperCase() ?? '—'}
          </div>
        </div>
        <div className="bg-gray-900 rounded-xl p-3 border border-gray-700">
          <div className="text-xs text-gray-500 mb-1">Next Open</div>
          <div className="text-sm font-bold text-blue-400">
            {sentinel ? minsToHM(sentinel.minutes_until_open) : '—'}
          </div>
        </div>
        <div className="bg-gray-900 rounded-xl p-3 border border-gray-700">
          <div className="text-xs text-gray-500 mb-1">Last Poll</div>
          <div className="text-sm font-bold text-gray-300">
            {fmtTime(sentinel?.last_poll ?? null)}
          </div>
        </div>
        <div className="bg-gray-900 rounded-xl p-3 border border-gray-700">
          <div className="text-xs text-gray-500 mb-1">Catalysts Found</div>
          <div className="text-sm font-bold text-amber-400">
            {sentinel?.catalyst_count ?? 0}
          </div>
        </div>
      </div>

      {/* ── View tabs ──────────────────────────────────────────────────── */}
      <div className="flex gap-2">
        <button
          onClick={() => setView('feed')}
          className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${activeView === 'feed' ? 'bg-amber-700 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}
        >
          Catalyst Feed
        </button>
        <button
          onClick={() => setView('impact')}
          className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${activeView === 'impact' ? 'bg-cyan-700 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}
        >
          News → Price Impact
        </button>
        {/* category pills */}
        {activeView === 'feed' && sortedCategories.map(cat => (
          <span key={cat} className={`text-xs px-2 py-1 rounded border ${categoryColor(cat)} font-semibold self-center`}>
            {cat} ({byCategory[cat].length})
          </span>
        ))}
      </div>

      {/* ── Catalyst Feed ──────────────────────────────────────────────── */}
      {activeView === 'feed' && (
        catalysts.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-gray-500 bg-gray-900 rounded-xl border border-gray-800">
            No catalysts detected yet — sentinel polls every 15 min when market is closed.
          </div>
        ) : (
          <div className="space-y-4">
            {sortedCategories.map(cat => (
              <div key={cat}>
                <div className={`text-xs font-bold uppercase tracking-widest mb-2 px-1 ${categoryColor(cat).split(' ')[1]}`}>
                  {cat} ({byCategory[cat].length})
                </div>
                <div className="space-y-2">
                  {byCategory[cat]
                    .sort((a, b) => b.score - a.score)
                    .map((c, i) => <CatalystCard key={i} cat={c} />)}
                </div>
              </div>
            ))}
          </div>
        )
      )}

      {/* ── News → Price Impact ────────────────────────────────────────── */}
      {activeView === 'impact' && (
        <div className="space-y-3">
          {(impact?.total ?? 0) === 0 ? (
            <div className="flex items-center justify-center h-40 text-gray-500 bg-gray-900 rounded-xl border border-gray-800">
              No price snapshots yet — impact data builds once catalysts are detected and the market opens.
            </div>
          ) : (
            <>
              {/* confirmed moves */}
              {(impact?.confirmed.length ?? 0) > 0 && (
                <div>
                  <div className="text-xs font-bold text-emerald-400 uppercase tracking-widest mb-2">
                    Confirmed Moves ({impact!.confirmed.length})
                  </div>
                  <div className="bg-gray-900 rounded-xl border border-gray-700 overflow-hidden">
                    <div className="grid grid-cols-12 gap-2 px-3 py-2 bg-gray-800 text-xs text-gray-500 font-semibold">
                      <div className="col-span-1">SYM</div>
                      <div className="col-span-4">Catalyst</div>
                      <div className="col-span-1">Cat</div>
                      <div className="col-span-1">Price@</div>
                      <div className="col-span-2 text-center">At Open</div>
                      <div className="col-span-2 text-center">Sustained</div>
                      <div className="col-span-1 text-center">Status</div>
                    </div>
                    <div className="px-3">
                      {impact!.confirmed.map((s, i) => <ImpactRow key={i} snap={s} />)}
                    </div>
                  </div>
                </div>
              )}

              {/* pending */}
              {(impact?.pending.length ?? 0) > 0 && (
                <div>
                  <div className="text-xs font-bold text-yellow-500 uppercase tracking-widest mb-2">
                    Pending ({impact!.pending.length})
                  </div>
                  <div className="bg-gray-900 rounded-xl border border-gray-700 overflow-hidden">
                    <div className="grid grid-cols-12 gap-2 px-3 py-2 bg-gray-800 text-xs text-gray-500 font-semibold">
                      <div className="col-span-1">SYM</div>
                      <div className="col-span-4">Catalyst</div>
                      <div className="col-span-1">Cat</div>
                      <div className="col-span-1">Price@</div>
                      <div className="col-span-2 text-center">At Open</div>
                      <div className="col-span-2 text-center">Sustained</div>
                      <div className="col-span-1 text-center">Status</div>
                    </div>
                    <div className="px-3">
                      {impact!.pending.map((s, i) => <ImpactRow key={i} snap={s} />)}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
