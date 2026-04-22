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

type LeaderEntry = [string, number]

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

const BUTTON: React.CSSProperties = {
  background: 'var(--bg-input)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--text-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  padding: '2px 8px',
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
  cursor: 'pointer',
}

function consensusColor(c: string): string {
  if (c === 'STRONG BUY' || c === 'BUY')  return 'var(--accent-green)'
  if (c === 'STRONG SELL' || c === 'SELL') return 'var(--accent-red)'
  return 'var(--accent-amber)'
}

function returnColor(v: number): string {
  return v >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'
}

function actionColor(a: string): string {
  if (a === 'BUY')  return 'var(--accent-green)'
  if (a === 'SELL') return 'var(--accent-red)'
  return 'var(--text-dim)'
}

function AgentBlock({ name, s }: { name: string; s: AgentSummary }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ ...PANEL, marginBottom: 0 }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%',
          background: 'transparent',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
            {name}
          </span>
          <span style={{ ...LABEL, color: 'var(--accent-green)', border: '1px solid var(--accent-green)', padding: '0 4px' }}>
            {s.buy_count} BUY
          </span>
          <span style={{ ...LABEL, color: 'var(--accent-red)', border: '1px solid var(--accent-red)', padding: '0 4px' }}>
            {s.sell_count} SELL
          </span>
          <span style={{ ...LABEL, color: 'var(--text-secondary)', border: '1px solid var(--border-soft)', padding: '0 4px' }}>
            {s.hold_count} HOLD
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ ...NUM, fontSize: 12, fontWeight: 600, color: returnColor(s.total_return_pct) }}>
            {s.total_return_pct >= 0 ? '+' : ''}{s.total_return_pct.toFixed(2)}%
          </span>
          <span style={{ ...LABEL }}>{(s.win_rate * 100).toFixed(0)}% WIN</span>
          <span style={{ color: 'var(--accent-cyan)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--border-hair)', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {s.top_buys.length > 0 && (
            <div>
              <div style={{ ...LABEL, marginBottom: 3 }}>TOP BUYS</div>
              {s.top_buys.map(b => (
                <div key={b.symbol} style={{ display: 'flex', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 11, marginBottom: 1 }}>
                  <span style={{ color: 'var(--accent-green)', fontWeight: 600, width: 50 }}>{b.symbol}</span>
                  <span style={{ ...NUM, color: 'var(--text-dim)', width: 40 }}>{(b.confidence * 100).toFixed(0)}%</span>
                  <span style={{ color: 'var(--text-secondary)' }}>{b.reasoning}</span>
                </div>
              ))}
            </div>
          )}

          {s.top_sells.length > 0 && (
            <div>
              <div style={{ ...LABEL, marginBottom: 3 }}>TOP SELLS</div>
              {s.top_sells.map(b => (
                <div key={b.symbol} style={{ display: 'flex', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 11, marginBottom: 1 }}>
                  <span style={{ color: 'var(--accent-red)', fontWeight: 600, width: 50 }}>{b.symbol}</span>
                  <span style={{ ...NUM, color: 'var(--text-dim)', width: 40 }}>{(b.confidence * 100).toFixed(0)}%</span>
                  <span style={{ color: 'var(--text-secondary)' }}>{b.reasoning}</span>
                </div>
              ))}
            </div>
          )}

          {s.active_picks.length > 0 && (
            <div>
              <div style={{ ...LABEL, marginBottom: 3 }}>RETAINED PICKS</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {s.active_picks.map(sym => (
                  <span key={sym} style={{
                    ...LABEL,
                    color: 'var(--accent-cyan)',
                    border: '1px solid var(--accent-cyan)',
                    padding: '0 5px',
                  }}>{sym}</span>
                ))}
              </div>
            </div>
          )}

          {s.trades_today.length > 0 && (
            <div>
              <div style={{ ...LABEL, marginBottom: 3 }}>TRADES TODAY</div>
              {s.trades_today.map((t, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 11, marginBottom: 1 }}>
                  <span style={{ color: 'var(--text-dim)', width: 50 }}>{t.timestamp}</span>
                  <span style={{ color: actionColor(t.action), fontWeight: 600, width: 36 }}>{t.action}</span>
                  <span style={{ color: 'var(--accent-cyan)', fontWeight: 600, width: 50 }}>{t.symbol}</span>
                  <span style={{ ...NUM, color: 'var(--text-secondary)' }}>${t.price.toFixed(2)}</span>
                  {t.pnl != null && (
                    <span style={{ ...NUM, color: returnColor(t.pnl), marginLeft: 'auto' }}>
                      {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function SummaryPanelV2() {
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

  const genTime = data?.generated_at ? formatTime(data.generated_at, timeZone) : null
  const consensusEntries = Object.entries(data?.consensus ?? {}).slice(0, 10)
  const agentEntries     = Object.entries(data?.agent_summaries ?? {})

  return (
    <div>
      {/* Header */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>DAILY ROLL-UP · CONSENSUS · NARRATIVE</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {genTime && <span style={{ ...LABEL }}>GEN {genTime}</span>}
            {data?.market_status && (
              <span style={{
                ...LABEL,
                color: data.market_status === 'open' ? 'var(--accent-green)' : 'var(--accent-cyan)',
                border: `1px solid ${data.market_status === 'open' ? 'var(--accent-green)' : 'var(--accent-cyan)'}`,
                padding: '0 5px',
              }}>{data.market_status.toUpperCase()}</span>
            )}
            <button
              type="button"
              onClick={() => fetchSummary(true)}
              disabled={loading}
              style={{
                ...BUTTON,
                color: loading ? 'var(--text-dim)' : 'var(--accent-amber)',
                borderColor: loading ? 'var(--border-hair)' : 'var(--accent-amber)',
                cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >{loading ? 'GENERATING…' : '◈ REFRESH'}</button>
          </div>
        </div>
        <div style={{ ...LABEL }}>
          AGENT DECISIONS · CROSS-AGENT CONSENSUS · CLAUDE-AUTHORED NARRATIVE
        </div>
      </div>

      {error && (
        <div style={{
          ...PANEL,
          borderColor: 'var(--accent-red)',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--accent-red)',
        }}>ERROR: {error}</div>
      )}

      {loading && !data && (
        <div style={{
          ...PANEL,
          borderStyle: 'dashed',
          textAlign: 'center',
          padding: 20,
          fontFamily: 'var(--font-mono)',
          letterSpacing: '0.12em',
          color: 'var(--accent-amber)',
        }}>
          ◈ GENERATING DAILY ROLL-UP…
        </div>
      )}

      {data && data.status !== 'error' && (
        <>
          {/* Narrative */}
          {data.narrative && (
            <div style={{ ...PANEL, borderColor: 'var(--accent-amber)' }}>
              <div style={HEADER}>
                <span>AI NARRATIVE · {data.date}</span>
              </div>
              <p style={{
                margin: 0,
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--text-primary)',
                lineHeight: 1.55,
                whiteSpace: 'pre-line',
              }}>{data.narrative}</p>
            </div>
          )}

          {/* Leaderboard */}
          {data.leaderboard && data.leaderboard.length > 0 && (
            <div style={PANEL}>
              <div style={HEADER}>
                <span>TODAY&apos;S AGENT RANKING</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                {data.leaderboard.map(([name, ret], i) => (
                  <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 4, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                    <span style={{ color: 'var(--text-dim)' }}>#{i + 1}</span>
                    <span style={{ color: 'var(--text-primary)' }}>{name}</span>
                    <span style={{ ...NUM, color: returnColor(ret), fontWeight: 600 }}>
                      {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Two-column: consensus + trades today */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 8, marginBottom: 8 }}>
            <div style={{ ...PANEL, marginBottom: 0 }}>
              <div style={HEADER}>
                <span>CROSS-AGENT CONSENSUS · {consensusEntries.length}</span>
              </div>
              {consensusEntries.length === 0 ? (
                <div style={{ ...LABEL, padding: '6px 0' }}>NO CONSENSUS DATA YET</div>
              ) : (
                <div>
                  {consensusEntries.map(([sym, c]) => (
                    <div key={sym} style={{
                      borderTop: '1px solid var(--border-hair)',
                      padding: '4px 0',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ color: 'var(--accent-cyan)', fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: 11, width: 50 }}>{sym}</span>
                        <span style={{
                          ...LABEL,
                          color: consensusColor(c.consensus),
                          border: `1px solid ${consensusColor(c.consensus)}`,
                          padding: '0 5px',
                        }}>{c.consensus}</span>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ ...LABEL, color: 'var(--text-secondary)' }}>
                          {(c.agreement * 100).toFixed(0)}% AGREE
                        </div>
                        <div style={{ ...LABEL }}>
                          {c.buy_votes.length}↑ {c.sell_votes.length}↓
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div style={{ ...PANEL, marginBottom: 0 }}>
              <div style={HEADER}>
                <span>TRADES TODAY · {data.trades_today?.length ?? 0}</span>
              </div>
              {(!data.trades_today || data.trades_today.length === 0) ? (
                <div style={{ ...LABEL, padding: '6px 0' }}>NO TRADES EXECUTED TODAY</div>
              ) : (
                <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                  {data.trades_today.map((t, i) => (
                    <div key={i} style={{
                      borderTop: '1px solid var(--border-hair)',
                      padding: '4px 0',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11,
                    }}>
                      <span style={{ color: 'var(--text-dim)', width: 45 }}>{t.timestamp}</span>
                      <span style={{ color: actionColor(t.action), fontWeight: 600, width: 36 }}>{t.action}</span>
                      <span style={{ color: 'var(--accent-cyan)', fontWeight: 600, width: 50 }}>{t.symbol}</span>
                      <span style={{ color: 'var(--text-secondary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.agent}</span>
                      {t.pnl != null && (
                        <span style={{ ...NUM, color: returnColor(t.pnl) }}>
                          {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Per-agent breakdowns */}
          <div style={PANEL}>
            <div style={HEADER}>
              <span>AGENT BREAKDOWNS · {agentEntries.length}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {agentEntries.map(([name, s]) => (
                <AgentBlock key={name} name={name} s={s} />
              ))}
            </div>
          </div>

          {/* Ensemble strip */}
          {data.ensemble && (
            <div style={PANEL}>
              <div style={HEADER}>
                <span>ENSEMBLE</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                <div>
                  <span style={LABEL}>REGIME </span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{data.ensemble.regime.toUpperCase()}</span>
                </div>
                <div>
                  <span style={LABEL}>RETURN </span>
                  <span style={{ ...NUM, color: returnColor(data.ensemble.total_return_pct), fontWeight: 600 }}>
                    {data.ensemble.total_return_pct >= 0 ? '+' : ''}{data.ensemble.total_return_pct.toFixed(2)}%
                  </span>
                </div>
                <div>
                  <span style={LABEL}>WIN RATE </span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{(data.ensemble.win_rate * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {data?.status === 'error' && (
        <div style={{
          ...PANEL,
          borderColor: 'var(--accent-red)',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--accent-red)',
        }}>{data.error || 'SUMMARY GENERATION FAILED'}</div>
      )}
    </div>
  )
}
