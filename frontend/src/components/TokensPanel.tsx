import React, { useEffect, useState, useCallback } from 'react'

const API_BASE = ''

interface TokenLogEntry {
  id: number
  timestamp: string
  agent: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  daily_total: number
  daily_limit: number | null
  limit_hit: boolean
}

interface TokenStats {
  daily_tokens: number
  session_tokens: number
  calls_this_hour: number
  hourly_call_limit: number | null
  daily_limit?: number
  daily_remaining?: number
}

interface TokenStatsData {
  agents: Record<string, TokenStats>
  totals: { daily_tokens: number; session_tokens: number }
}

const AGENT_COLORS: Record<string, string> = {
  SentimentAgent: 'text-green-400',
  ClaudeAgent:    'text-red-400',
  GeminiAgent:    'text-blue-400',
}

function agentBadge(agent: string) {
  const color = AGENT_COLORS[agent] || 'text-gray-400'
  return <span className={`font-semibold ${color}`}>{agent}</span>
}

export default function TokensPanel() {
  const [entries, setEntries] = useState<TokenLogEntry[]>([])
  const [stats, setStats] = useState<TokenStatsData | null>(null)
  const [agentFilter, setAgentFilter] = useState<string>('')
  const [hoursFilter, setHoursFilter] = useState<number>(24)
  const [limitHitOnly, setLimitHitOnly] = useState<boolean>(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchLog = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (agentFilter) params.set('agent', agentFilter)
      params.set('hours', String(hoursFilter))
      if (limitHitOnly) params.set('limit_hit', 'true')
      const resp = await fetch(`${API_BASE}/api/token-log?${params}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setEntries(data.entries || [])
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [agentFilter, hoursFilter, limitHitOnly])

  const fetchStats = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/tokens`)
      if (!resp.ok) return
      const data = await resp.json()
      setStats(data)
    } catch {}
  }, [])

  useEffect(() => {
    fetchLog()
    fetchStats()
  }, [fetchLog, fetchStats])

  // Auto-refresh every 30s
  useEffect(() => {
    const id = setInterval(() => {
      fetchLog()
      fetchStats()
    }, 30_000)
    return () => clearInterval(id)
  }, [fetchLog, fetchStats])

  const limitHitEntries = entries.filter(e => e.limit_hit)
  const hasAlert = limitHitEntries.length > 0

  return (
    <div className="space-y-4">

      {/* Alert banner */}
      {hasAlert && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-orange-900/50 border border-orange-600 text-orange-300 text-sm">
          <span className="text-lg">⚠️</span>
          <span>
            <span className="font-bold">Token limit reached</span> — {limitHitEntries.length} event{limitHitEntries.length > 1 ? 's' : ''} in the last {hoursFilter}h.
            Affected: {[...new Set(limitHitEntries.map(e => e.agent))].join(', ')}
          </span>
        </div>
      )}

      {/* Live stats */}
      {stats && (
        <div className="card">
          <div className="card-header mb-3">Live Token Stats</div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.entries(stats.agents).map(([name, s]) => (
              <div key={name} className="bg-gray-800/60 rounded-lg p-3 border border-gray-700/40">
                <div className="text-xs font-semibold mb-2">{agentBadge(name)}</div>
                <div className="flex flex-col gap-1 text-xs text-gray-400">
                  <div className="flex justify-between">
                    <span>Today</span>
                    <span className="text-white font-medium">{s.daily_tokens.toLocaleString()} tok</span>
                  </div>
                  {s.daily_limit != null && (
                    <div className="flex justify-between">
                      <span>Remaining</span>
                      <span className={`font-medium ${(s.daily_remaining ?? 0) < 1000 ? 'text-orange-400' : 'text-green-400'}`}>
                        {(s.daily_remaining ?? 0).toLocaleString()}
                      </span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span>Calls/hr</span>
                    <span className="text-white">{s.calls_this_hour}/{s.hourly_call_limit ?? '∞'}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-gray-700/40 flex gap-6 text-xs text-gray-400">
            <span>Total today: <span className="text-white font-medium">{stats.totals.daily_tokens.toLocaleString()} tokens</span></span>
            <span>Session: <span className="text-white font-medium">{stats.totals.session_tokens.toLocaleString()} tokens</span></span>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span>Agent:</span>
            <select
              value={agentFilter}
              onChange={e => setAgentFilter(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs"
            >
              <option value="">All</option>
              <option value="SentimentAgent">SentimentAgent</option>
              <option value="ClaudeAgent">ClaudeAgent</option>
              <option value="GeminiAgent">GeminiAgent</option>
            </select>
          </div>

          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span>Window:</span>
            <select
              value={hoursFilter}
              onChange={e => setHoursFilter(Number(e.target.value))}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs"
            >
              <option value={1}>Last 1h</option>
              <option value={6}>Last 6h</option>
              <option value={12}>Last 12h</option>
              <option value={24}>Last 24h</option>
            </select>
          </div>

          <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              checked={limitHitOnly}
              onChange={e => setLimitHitOnly(e.target.checked)}
              className="rounded"
            />
            Limit-hit only
          </label>

          <button
            onClick={() => { fetchLog(); fetchStats() }}
            className="ml-auto px-3 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-white transition-colors"
          >
            {loading ? '...' : '⟳ Refresh'}
          </button>
        </div>
      </div>

      {/* Log table */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <span className="card-header mb-0">Token Log</span>
          <span className="text-xs text-gray-500">{entries.length} entries</span>
        </div>

        {error && (
          <div className="text-red-400 text-sm py-2">{error}</div>
        )}

        {entries.length === 0 && !loading && !error ? (
          <p className="text-center text-gray-500 text-sm py-6">No token log entries found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-2 pr-3 font-medium">Time</th>
                  <th className="text-left py-2 pr-3 font-medium">Agent</th>
                  <th className="text-left py-2 pr-3 font-medium">Model</th>
                  <th className="text-right py-2 pr-3 font-medium">Prompt</th>
                  <th className="text-right py-2 pr-3 font-medium">Completion</th>
                  <th className="text-right py-2 pr-3 font-medium">Total</th>
                  <th className="text-right py-2 pr-3 font-medium">Day Total</th>
                  <th className="text-center py-2 font-medium">Limit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {entries.map(entry => (
                  <tr key={entry.id} className={`hover:bg-gray-800/30 ${entry.limit_hit ? 'bg-orange-900/20' : ''}`}>
                    <td className="py-1.5 pr-3 text-gray-500 font-mono whitespace-nowrap">
                      {new Date(entry.timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </td>
                    <td className="py-1.5 pr-3">{agentBadge(entry.agent)}</td>
                    <td className="py-1.5 pr-3 text-gray-400">{entry.model}</td>
                    <td className="py-1.5 pr-3 text-right text-gray-300 font-mono">{entry.prompt_tokens.toLocaleString()}</td>
                    <td className="py-1.5 pr-3 text-right text-gray-300 font-mono">{entry.completion_tokens.toLocaleString()}</td>
                    <td className="py-1.5 pr-3 text-right text-white font-mono font-medium">{entry.total_tokens.toLocaleString()}</td>
                    <td className="py-1.5 pr-3 text-right text-gray-400 font-mono">{entry.daily_total.toLocaleString()}</td>
                    <td className="py-1.5 text-center">
                      {entry.limit_hit
                        ? <span className="px-1.5 py-0.5 rounded text-xs bg-orange-800 text-orange-300 font-medium">HIT</span>
                        : <span className="text-gray-600">—</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
