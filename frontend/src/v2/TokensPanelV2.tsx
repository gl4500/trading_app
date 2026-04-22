import React, { useEffect, useState, useCallback } from 'react'
import { useTimezone } from '../context/TimezoneContext'
import { formatDate, formatTime } from '../utils/time'

const API_BASE = ''

interface TokenLogEntry {
  id: number
  date: string
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
  SentimentAgent:        'var(--accent-green)',
  ClaudeAgent:           'var(--accent-red)',
  GeminiAgent:           'var(--accent-cyan)',
  SummaryAgent:          'var(--accent-amber)',
  'ScannerAgent/Claude': 'var(--accent-red)',
  'ScannerAgent/Gemini': 'var(--accent-cyan)',
  'ScannerAgent/OpenAI': 'var(--accent-green)',
  'ScannerAgent/Ollama': 'var(--accent-violet)',
}

const PANEL: React.CSSProperties = {
  background: 'var(--bg-panel)',
  border: '1px solid var(--border-hair)',
  borderRadius: 'var(--radius-sm)',
  padding: '8px 10px',
  marginBottom: 8,
}

const HEADER: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 12,
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  letterSpacing: '0.15em',
  textTransform: 'uppercase',
  color: 'var(--accent-amber)',
  paddingBottom: 6,
  marginBottom: 8,
  borderBottom: '1px solid var(--border-hair)',
}

const LABEL: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--text-dim)',
}

const NUM: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontVariantNumeric: 'tabular-nums',
}

const SELECT: React.CSSProperties = {
  background: 'var(--bg-input)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--text-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  padding: '2px 6px',
}

const TH: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.12em',
  color: 'var(--text-dim)',
  textTransform: 'uppercase',
  padding: '4px 6px',
  fontWeight: 500,
  borderBottom: '1px solid var(--border-hair)',
  textAlign: 'left',
}

const TD: React.CSSProperties = {
  padding: '4px 6px',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontVariantNumeric: 'tabular-nums',
  color: 'var(--text-primary)',
}

function agentColor(name: string): string {
  return AGENT_COLORS[name] || 'var(--text-secondary)'
}

export default function TokensPanelV2() {
  const { timeZone } = useTimezone()
  const [entries, setEntries] = useState<TokenLogEntry[]>([])
  const [stats, setStats] = useState<TokenStatsData | null>(null)
  const [agentFilter, setAgentFilter] = useState<string>('')
  const [hoursFilter, setHoursFilter] = useState<number>(24)
  const [limitHitOnly, setLimitHitOnly] = useState<boolean>(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)

  const fetchLog = useCallback(async () => {
    setLoading(true)
    setError(null)
    setOffline(false)
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
      if (e instanceof TypeError) setOffline(true)
      else setError(e.message)
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
    <div>
      {/* Alert banner */}
      {hasAlert && (
        <div style={{
          ...PANEL,
          borderColor: 'var(--accent-amber)',
          borderLeft: '3px solid var(--accent-amber)',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--accent-amber)',
          letterSpacing: '0.1em',
        }}>
          ⚠ TOKEN LIMIT HIT — {limitHitEntries.length} EVENT{limitHitEntries.length > 1 ? 'S' : ''} IN LAST {hoursFilter}H ·{' '}
          AFFECTED: {[...new Set(limitHitEntries.map(e => e.agent))].join(', ')}
        </div>
      )}

      {/* Live stats */}
      {stats && Object.keys(stats.agents).length > 0 && (
        <div style={PANEL}>
          <div style={HEADER}>
            <span>LIVE TOKEN STATS</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 6 }}>
            {Object.entries(stats.agents).map(([name, s]) => (
              <div key={name} style={{ background: 'var(--bg-input)', border: '1px solid var(--border-hair)', padding: '4px 8px' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, color: agentColor(name), marginBottom: 4 }}>
                  {name}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-dim)' }}>TODAY</span>
                    <span style={{ ...NUM, color: 'var(--text-primary)' }}>{s.daily_tokens.toLocaleString()} TOK</span>
                  </div>
                  {s.daily_limit != null && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-dim)' }}>REMAINING</span>
                      <span style={{ ...NUM, color: (s.daily_remaining ?? 0) < 1000 ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
                        {(s.daily_remaining ?? 0).toLocaleString()}
                      </span>
                    </div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-dim)' }}>CALLS/HR</span>
                    <span style={{ ...NUM, color: 'var(--text-primary)' }}>{s.calls_this_hour}/{s.hourly_call_limit ?? '∞'}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div style={{
            marginTop: 6,
            paddingTop: 6,
            borderTop: '1px solid var(--border-hair)',
            display: 'flex',
            gap: 14,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
          }}>
            <span>
              <span style={LABEL}>TOTAL TODAY </span>
              <span style={{ ...NUM, color: 'var(--text-primary)', fontWeight: 600 }}>{stats.totals.daily_tokens.toLocaleString()}</span>
            </span>
            <span>
              <span style={LABEL}>SESSION </span>
              <span style={{ ...NUM, color: 'var(--text-primary)', fontWeight: 600 }}>{stats.totals.session_tokens.toLocaleString()}</span>
            </span>
          </div>
        </div>
      )}

      {/* Filters */}
      <div style={PANEL}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={LABEL}>AGENT</span>
            <select
              aria-label="Agent filter"
              value={agentFilter}
              onChange={e => setAgentFilter(e.target.value)}
              style={SELECT}
            >
              <option value="">ALL</option>
              <option value="SentimentAgent">SentimentAgent</option>
              <option value="ClaudeAgent">ClaudeAgent</option>
              <option value="GeminiAgent">GeminiAgent</option>
              <option value="SummaryAgent">SummaryAgent</option>
              <option value="ScannerAgent/Claude">ScannerAgent/Claude</option>
              <option value="ScannerAgent/Gemini">ScannerAgent/Gemini</option>
              <option value="ScannerAgent/OpenAI">ScannerAgent/OpenAI</option>
              <option value="ScannerAgent/Ollama">ScannerAgent/Ollama</option>
            </select>
          </label>

          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={LABEL}>WINDOW</span>
            <select
              aria-label="Window filter"
              value={hoursFilter}
              onChange={e => setHoursFilter(Number(e.target.value))}
              style={SELECT}
            >
              <option value={1}>LAST 1H</option>
              <option value={6}>LAST 6H</option>
              <option value={12}>LAST 12H</option>
              <option value={24}>LAST 24H</option>
              <option value={168}>LAST 7D</option>
              <option value={720}>LAST 30D</option>
              <option value={0}>ALL TIME</option>
            </select>
          </label>

          <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={limitHitOnly}
              onChange={e => setLimitHitOnly(e.target.checked)}
            />
            <span style={LABEL}>LIMIT-HIT ONLY</span>
          </label>

          <button
            type="button"
            onClick={() => { fetchLog(); fetchStats() }}
            style={{ ...SELECT, marginLeft: 'auto', cursor: 'pointer', color: 'var(--accent-cyan)' }}
          >
            {loading ? '…' : '⟳ REFRESH'}
          </button>
        </div>
      </div>

      {/* Log table */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>TOKEN LOG · {entries.length} ENTRIES</span>
        </div>

        {offline && (
          <div style={{
            border: '1px solid var(--accent-red)',
            background: 'var(--bg-input)',
            padding: '6px 10px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--accent-red)',
          }}>
            ⚠ BACKEND OFFLINE — START THE APP AND TRY AGAIN
          </div>
        )}

        {error && !offline && (
          <div style={{
            border: '1px solid var(--accent-red)',
            background: 'var(--bg-input)',
            padding: '6px 10px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--accent-red)',
          }}>
            API ERROR: {error}
          </div>
        )}

        {!offline && entries.length === 0 && !loading && !error ? (
          <div style={{
            textAlign: 'center', padding: 18,
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--text-dim)', letterSpacing: '0.12em',
            border: '1px dashed var(--border-soft)',
          }}>
            NO TOKEN LOG ENTRIES FOUND
          </div>
        ) : !offline && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={TH}>DATE</th>
                  <th style={TH}>TIME</th>
                  <th style={TH}>AGENT</th>
                  <th style={TH}>MODEL</th>
                  <th style={{ ...TH, textAlign: 'right' }}>PROMPT</th>
                  <th style={{ ...TH, textAlign: 'right' }}>COMPL</th>
                  <th style={{ ...TH, textAlign: 'right' }}>TOTAL</th>
                  <th style={{ ...TH, textAlign: 'right' }}>DAY</th>
                  <th style={{ ...TH, textAlign: 'center' }}>LIMIT</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(entry => (
                  <tr key={entry.id} style={{
                    borderTop: '1px solid var(--border-hair)',
                    background: entry.limit_hit ? 'rgba(251, 191, 36, 0.08)' : 'transparent',
                  }}>
                    <td style={{ ...TD, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                      {entry.date || formatDate(entry.timestamp, timeZone)}
                    </td>
                    <td style={{ ...TD, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                      {formatTime(entry.timestamp, timeZone)}
                    </td>
                    <td style={{ ...TD, color: agentColor(entry.agent), fontWeight: 600 }}>
                      {entry.agent}
                    </td>
                    <td style={{ ...TD, color: 'var(--text-secondary)' }}>{entry.model}</td>
                    <td style={{ ...TD, textAlign: 'right' }}>{entry.prompt_tokens.toLocaleString()}</td>
                    <td style={{ ...TD, textAlign: 'right' }}>{entry.completion_tokens.toLocaleString()}</td>
                    <td style={{ ...TD, textAlign: 'right', fontWeight: 600 }}>{entry.total_tokens.toLocaleString()}</td>
                    <td style={{ ...TD, textAlign: 'right', color: 'var(--text-secondary)' }}>{entry.daily_total.toLocaleString()}</td>
                    <td style={{ ...TD, textAlign: 'center' }}>
                      {entry.limit_hit
                        ? <span style={{ ...LABEL, color: 'var(--accent-amber)', border: '1px solid var(--accent-amber)', padding: '0 5px' }}>HIT</span>
                        : <span style={{ ...LABEL }}>—</span>
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
