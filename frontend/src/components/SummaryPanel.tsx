import React, { useEffect, useState } from 'react'
import { useTimezone } from '../context/TimezoneContext'
import { formatTime } from '../utils/time'

const API_BASE = ''

interface AgentSummary {
  buy_count: number
  sell_count: number
  hold_count: number
  total_return_pct: number
  win_rate: number
  active_picks: string[]
  top_buys: { symbol: string; confidence: number; reasoning: string }[]
  top_sells: { symbol: string; confidence: number; reasoning: string }[]
  trades_today: { symbol: string; action: string; price: number; pnl: number | null; timestamp: string }[]
}

interface ConsensusEntry {
  consensus: string
  buy_votes:  { agent: string; confidence: number }[]
  sell_votes: { agent: string; confidence: number }[]
  agreement: number
}

interface TradeToday {
  agent: string
  symbol: string
  action: string
  shares: number
  price: number
  pnl: number | null
  timestamp: string
  reasoning: string
}

interface LeaderEntry { 0: string; 1: number }

interface SummaryData {
  status: string
  error?: string
  generated_at: string
  date: string
  market_status: string
  narrative: string
  agent_summaries: Record<string, AgentSummary>
  consensus: Record<string, ConsensusEntry>
  leaderboard: LeaderEntry[]
  trades_today: TradeToday[]
  ensemble?: { total_return_pct: number; win_rate: number; regime: string }
  scanner_recs: { symbol: string; action: string; confidence: number; reasoning: string }[]
}

// ── helpers ──────────────────────────────────────────────────────────────────

function consensusColor(c: string) {
  if (c === 'STRONG BUY')  return 'text-emerald-400'
  if (c === 'BUY')         return 'text-green-400'
  if (c === 'STRONG SELL') return 'text-red-500'
  if (c === 'SELL')        return 'text-red-400'
  return 'text-yellow-400'
}

function consensusBadge(c: string) {
  if (c === 'STRONG BUY')  return 'bg-emerald-900 border-emerald-600 text-emerald-300'
  if (c === 'BUY')         return 'bg-green-900 border-green-700 text-green-300'
  if (c === 'STRONG SELL') return 'bg-red-900 border-red-500 text-red-200'
  if (c === 'SELL')        return 'bg-red-900 border-red-700 text-red-300'
  return 'bg-yellow-900 border-yellow-700 text-yellow-300'
}

function returnColor(v: number) {
  return v >= 0 ? 'text-emerald-400' : 'text-red-400'
}

function actionColor(a: string) {
  if (a === 'BUY')  return 'text-emerald-400'
  if (a === 'SELL') return 'text-red-400'
  return 'text-gray-400'
}

// ── Sub-components ────────────────────────────────────────────────────────────

function AgentRow({ name, s }: { name: string; s: AgentSummary }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-gray-700 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-800 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-white font-semibold text-sm">{name}</span>
          <span className="text-xs px-1.5 py-0.5 bg-emerald-900 text-emerald-300 rounded font-mono">
            {s.buy_count} BUY
          </span>
          <span className="text-xs px-1.5 py-0.5 bg-red-900 text-red-300 rounded font-mono">
            {s.sell_count} SELL
          </span>
          <span className="text-xs px-1.5 py-0.5 bg-gray-700 text-gray-300 rounded font-mono">
            {s.hold_count} HOLD
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className={`text-sm font-mono font-bold ${returnColor(s.total_return_pct)}`}>
            {s.total_return_pct >= 0 ? '+' : ''}{s.total_return_pct.toFixed(2)}%
          </span>
          <span className="text-xs text-gray-500">{(s.win_rate * 100).toFixed(0)}% win</span>
          <span className="text-gray-600 text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 bg-gray-900/60">

          {s.top_buys.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1.5">Top Buys</p>
              <div className="space-y-1">
                {s.top_buys.map(b => (
                  <div key={b.symbol} className="flex items-start gap-2 text-xs">
                    <span className="text-emerald-400 font-bold w-12 shrink-0">{b.symbol}</span>
                    <span className="text-gray-500 font-mono w-10 shrink-0">{(b.confidence * 100).toFixed(0)}%</span>
                    <span className="text-gray-400">{b.reasoning}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {s.top_sells.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1.5">Top Sells</p>
              <div className="space-y-1">
                {s.top_sells.map(b => (
                  <div key={b.symbol} className="flex items-start gap-2 text-xs">
                    <span className="text-red-400 font-bold w-12 shrink-0">{b.symbol}</span>
                    <span className="text-gray-500 font-mono w-10 shrink-0">{(b.confidence * 100).toFixed(0)}%</span>
                    <span className="text-gray-400">{b.reasoning}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {s.active_picks.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1.5">Retained Picks</p>
              <div className="flex flex-wrap gap-1.5">
                {s.active_picks.map(sym => (
                  <span key={sym} className="text-xs px-2 py-0.5 bg-blue-900/50 border border-blue-700 text-blue-300 rounded-full">
                    {sym}
                  </span>
                ))}
              </div>
            </div>
          )}

          {s.trades_today.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1.5">Trades Today</p>
              <div className="space-y-0.5">
                {s.trades_today.map((t, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className="text-gray-600 w-10 font-mono">{t.timestamp}</span>
                    <span className={`font-bold w-8 ${actionColor(t.action)}`}>{t.action}</span>
                    <span className="text-white font-medium w-12">{t.symbol}</span>
                    <span className="text-gray-400 font-mono">${t.price.toFixed(2)}</span>
                    {t.pnl != null && (
                      <span className={`ml-auto font-mono ${t.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function SummaryPanel() {
  const { timeZone } = useTimezone()
  const [data, setData]       = useState<SummaryData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  const fetchSummary = async (force = false) => {
    setLoading(true)
    setError(null)
    try {
      const url = force ? `${API_BASE}/api/summary?force=true` : `${API_BASE}/api/summary`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchSummary() }, [])

  const genTime = data?.generated_at
    ? formatTime(data.generated_at, timeZone)
    : null

  const consensusEntries = Object.entries(data?.consensus ?? {}).slice(0, 10)
  const agentEntries     = Object.entries(data?.agent_summaries ?? {})

  return (
    <div className="space-y-5">

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-white font-bold text-base flex items-center gap-2">
            <span className="text-amber-400">◈</span> Daily Roll-Up
          </h2>
          <p className="text-xs text-gray-500">
            Agent decisions · consensus map · Claude-authored narrative
          </p>
        </div>
        <div className="flex items-center gap-3">
          {genTime && <span className="text-xs text-gray-600">Generated: {genTime}</span>}
          {data?.market_status && (
            <span className={`text-xs px-2 py-0.5 rounded-full font-semibold border ${
              data.market_status === 'open'
                ? 'bg-emerald-900 border-emerald-700 text-emerald-300'
                : data.market_status.includes('market') || data.market_status === 'after-hours'
                ? 'bg-blue-900 border-blue-700 text-blue-300'
                : 'bg-gray-800 border-gray-600 text-gray-400'
            }`}>
              {data.market_status.toUpperCase()}
            </span>
          )}
          <button
            onClick={() => fetchSummary(true)}
            disabled={loading}
            className="text-xs px-3 py-1.5 bg-amber-700 hover:bg-amber-600 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg font-semibold transition-colors"
          >
            {loading ? 'Generating…' : '◈ Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 text-red-400 text-sm">{error}</div>
      )}

      {loading && !data && (
        <div className="bg-gray-900 border border-gray-700 rounded-xl p-8 text-center space-y-3">
          <div className="flex justify-center">
            <span className="animate-spin w-6 h-6 border-2 border-amber-500 border-t-transparent rounded-full inline-block" />
          </div>
          <p className="text-amber-300 font-semibold">Generating daily roll-up…</p>
          <p className="text-xs text-gray-600">Claude is synthesising agent decisions</p>
        </div>
      )}

      {data && data.status !== 'error' && (
        <>
          {/* Narrative */}
          {data.narrative && (
            <div className="bg-gray-900 border border-amber-800/50 rounded-xl p-5">
              <p className="text-xs text-amber-500 uppercase tracking-wider font-semibold mb-3">
                AI Narrative — {data.date}
              </p>
              <p className="text-gray-200 text-sm leading-relaxed whitespace-pre-line">
                {data.narrative}
              </p>
            </div>
          )}

          {/* Leaderboard strip */}
          {data.leaderboard && data.leaderboard.length > 0 && (
            <div className="bg-gray-900 border border-gray-700 rounded-xl px-4 py-3">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2 font-semibold">
                Today's Agent Ranking
              </p>
              <div className="flex flex-wrap gap-3">
                {data.leaderboard.map(([name, ret], i) => (
                  <div key={name} className="flex items-center gap-1.5">
                    <span className="text-gray-600 text-xs">#{i + 1}</span>
                    <span className="text-gray-300 text-xs font-medium">{name}</span>
                    <span className={`text-xs font-mono font-bold ${returnColor(ret)}`}>
                      {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Two-column: consensus + agents */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

            {/* Consensus map */}
            <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-800">
                <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold">
                  Cross-Agent Consensus ({consensusEntries.length})
                </p>
              </div>
              <div className="divide-y divide-gray-800">
                {consensusEntries.length === 0 && (
                  <p className="px-4 py-4 text-xs text-gray-600">No consensus data yet — waiting for agent signals.</p>
                )}
                {consensusEntries.map(([sym, c]) => (
                  <div key={sym} className="px-4 py-2.5 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-white font-bold text-sm w-14">{sym}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded border font-semibold ${consensusBadge(c.consensus)}`}>
                        {c.consensus}
                      </span>
                    </div>
                    <div className="flex flex-col items-end">
                      <span className="text-xs text-gray-500">
                        {(c.agreement * 100).toFixed(0)}% agreement
                      </span>
                      <span className="text-xs text-gray-600">
                        {c.buy_votes.length}↑ {c.sell_votes.length}↓
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Trades today */}
            <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-gray-800">
                <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold">
                  Trades Today ({data.trades_today?.length ?? 0})
                </p>
              </div>
              <div className="divide-y divide-gray-800 max-h-64 overflow-y-auto">
                {(!data.trades_today || data.trades_today.length === 0) && (
                  <p className="px-4 py-4 text-xs text-gray-600">No trades executed today.</p>
                )}
                {data.trades_today?.map((t, i) => (
                  <div key={i} className="px-4 py-2 flex items-center gap-2 text-xs">
                    <span className="text-gray-600 font-mono w-10">{t.timestamp}</span>
                    <span className={`font-bold w-8 ${actionColor(t.action)}`}>{t.action}</span>
                    <span className="text-white font-medium w-12">{t.symbol}</span>
                    <span className="text-gray-500 text-xs truncate flex-1">{t.agent}</span>
                    {t.pnl != null && (
                      <span className={`font-mono shrink-0 ${t.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Per-agent breakdowns */}
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-3">
              Agent Breakdowns
            </p>
            <div className="space-y-2">
              {agentEntries.map(([name, s]) => (
                <AgentRow key={name} name={name} s={s} />
              ))}
            </div>
          </div>

          {/* Ensemble strip */}
          {data.ensemble && (
            <div className="bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 flex flex-wrap gap-4 text-xs">
              <span className="text-gray-500 uppercase tracking-wider font-semibold self-center">Ensemble</span>
              <span className="text-gray-400">
                Regime: <span className="text-white font-semibold">{data.ensemble.regime.toUpperCase()}</span>
              </span>
              <span className="text-gray-400">
                Return: <span className={`font-mono font-bold ${returnColor(data.ensemble.total_return_pct)}`}>
                  {data.ensemble.total_return_pct >= 0 ? '+' : ''}{data.ensemble.total_return_pct.toFixed(2)}%
                </span>
              </span>
              <span className="text-gray-400">
                Win rate: <span className="text-white font-semibold">{(data.ensemble.win_rate * 100).toFixed(0)}%</span>
              </span>
            </div>
          )}
        </>
      )}

      {data?.status === 'error' && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 text-red-400 text-sm">
          {data.error || 'Summary generation failed.'}
        </div>
      )}
    </div>
  )
}
