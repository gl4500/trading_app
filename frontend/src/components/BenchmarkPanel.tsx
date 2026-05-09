import React, { useEffect, useState } from 'react'

// 2026-05-09 (#83): Portfolio vs SPY vs DJIA glance widget. Polls
// /api/benchmarks (cached server-side for 5 min) so the user can see
// each agent's since-inception return alongside the broad-market and
// DOW returns over the same window.

interface AgentReturn {
  name: string
  return_pct: number
  total_value: number
}

interface BenchmarkData {
  period_days: number
  as_of: string
  spy_return_pct: number | null
  dji_return_pct: number | null
  agents: AgentReturn[]
}

const REFRESH_MS = 5 * 60 * 1000   // 5 min — matches backend cache TTL

function formatPct(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(pct)) return '—'
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

function pctColor(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(pct)) return 'text-gray-400'
  if (pct > 0) return 'text-green-400'
  if (pct < 0) return 'text-red-400'
  return 'text-gray-300'
}

export default function BenchmarkPanel() {
  const [data, setData] = useState<BenchmarkData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState<boolean>(true)

  useEffect(() => {
    let cancelled = false

    async function fetchBenchmarks() {
      try {
        const res = await fetch('/api/benchmarks')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const body: BenchmarkData = await res.json()
        if (!cancelled) {
          setData(body)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'fetch failed')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchBenchmarks()
    const id = setInterval(fetchBenchmarks, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  if (loading && !data) {
    return (
      <div className="bg-gray-900 rounded-lg p-3 border border-gray-800">
        <div className="text-xs text-gray-500">Loading benchmarks…</div>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="bg-gray-900 rounded-lg p-3 border border-gray-800">
        <div className="text-xs text-red-400">Benchmarks unavailable: {error}</div>
      </div>
    )
  }

  if (!data) return null

  const periodLabel = data.period_days >= 30
    ? `${Math.round(data.period_days)} days`
    : `${data.period_days} days`

  // Top 5 agents to keep the widget compact; the leaderboard already shows the full list.
  const topAgents = data.agents.slice(0, 5)

  return (
    <div className="bg-gray-900 rounded-lg p-3 border border-gray-800">
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-200">
          Benchmarks <span className="text-xs text-gray-500 font-normal">({periodLabel})</span>
        </h3>
        <div className="text-xs text-gray-500">
          {data.as_of ? new Date(data.as_of).toLocaleTimeString() : ''}
        </div>
      </div>

      {/* Index row — SPY + DJIA side by side */}
      <div className="grid grid-cols-2 gap-2 mb-2 text-sm">
        <div className="bg-gray-800 rounded px-2 py-1.5">
          <div className="text-xs text-gray-500">SPY</div>
          <div className={`font-mono font-semibold ${pctColor(data.spy_return_pct)}`}>
            {formatPct(data.spy_return_pct)}
          </div>
        </div>
        <div className="bg-gray-800 rounded px-2 py-1.5">
          <div className="text-xs text-gray-500">DJIA</div>
          <div className={`font-mono font-semibold ${pctColor(data.dji_return_pct)}`}>
            {formatPct(data.dji_return_pct)}
          </div>
        </div>
      </div>

      {/* Top agents — with delta vs SPY for quick alpha glance */}
      <div className="space-y-0.5 text-xs">
        {topAgents.length === 0 ? (
          <div className="text-gray-500">No agent data yet.</div>
        ) : (
          topAgents.map((a) => {
            const spyDelta = data.spy_return_pct != null
              ? a.return_pct - data.spy_return_pct
              : null
            return (
              <div key={a.name} className="flex justify-between gap-2 items-baseline">
                <span className="text-gray-300 truncate" title={a.name}>{a.name}</span>
                <span className="flex items-baseline gap-2 font-mono">
                  <span className={pctColor(a.return_pct)}>{formatPct(a.return_pct)}</span>
                  {spyDelta != null && (
                    <span
                      className={`text-[10px] ${pctColor(spyDelta)}`}
                      title="vs SPY"
                    >
                      ({spyDelta >= 0 ? '+' : ''}{spyDelta.toFixed(1)} vs SPY)
                    </span>
                  )}
                </span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
