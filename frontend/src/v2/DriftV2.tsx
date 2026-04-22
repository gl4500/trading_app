import React, { useEffect, useState, useCallback } from 'react'

const API_BASE = ''

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

const REFRESH_BTN: React.CSSProperties = {
  background: 'var(--bg-input)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--accent-cyan)',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  padding: '2px 6px',
  letterSpacing: '0.05em',
  cursor: 'pointer',
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
  verticalAlign: 'top',
}

interface DriftReport {
  agent_name?: string
  is_drifting?: boolean
  alerts?: string[]
  message?: string
  reason?: string
  baseline_win_rate?: number
  recent_win_rate?: number
  current_win_rate?: number
  win_rate_change?: number
  baseline_avg_pnl_pct?: number
  recent_avg_pnl_pct?: number
  avg_pnl_change?: number
  total_trades?: number
  recent_window?: number
  [k: string]: any
}

interface DriftResponse {
  reports?: DriftReport[]
  drifting_agents?: number
  all_clear?: boolean
}

function num(v: number | undefined | null): number | null {
  return typeof v === 'number' && !Number.isNaN(v) ? v : null
}

function fmtPct(v: number | null, decimals = 1): string {
  return v == null ? '—' : `${v.toFixed(decimals)}%`
}

function fmtDelta(v: number | null, decimals = 1): string {
  if (v == null) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(decimals)}`
}

function deltaColor(v: number | null): string {
  if (v == null || v === 0) return 'var(--text-dim)'
  return v > 0 ? 'var(--accent-green)' : 'var(--accent-red)'
}

function fmtCount(v: number | undefined | null): string {
  return typeof v === 'number' ? v.toLocaleString('en-US') : '—'
}

function alertText(r: DriftReport): string | null {
  if (Array.isArray(r.alerts) && r.alerts.length > 0) return r.alerts.join(' · ')
  return r.message || r.reason || null
}

export default function DriftV2() {
  const [resp, setResp] = useState<DriftResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchDrift = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/drift`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setResp(data || {})
      setError(null)
    } catch (e: any) {
      setError(e?.message || 'unknown error')
      setResp(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDrift()
  }, [fetchDrift])

  const reports = resp?.reports ?? []
  const driftingCount = resp?.drifting_agents ?? reports.filter(r => r.is_drifting).length
  const allClear = resp?.all_clear ?? (driftingCount === 0)

  return (
    <div style={PANEL}>
      <div style={HEADER}>
        <span>AGENT DRIFT · {reports.length}</span>
        <button
          type="button"
          aria-label="Refresh drift"
          onClick={fetchDrift}
          style={REFRESH_BTN}
        >↻ REFRESH</button>
      </div>

      {loading && !resp && !error && (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--text-dim)', letterSpacing: '0.12em',
          border: '1px dashed var(--border-soft)',
        }}>
          LOADING DRIFT…
        </div>
      )}

      {error && (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--accent-red)', letterSpacing: '0.12em',
          border: '1px dashed var(--accent-red)',
        }}>
          DRIFT UNAVAILABLE — {error}
        </div>
      )}

      {!error && resp && (
        <>
          {/* Top summary */}
          <div style={{
            padding: '8px 12px',
            marginBottom: 10,
            border: `1px solid ${allClear ? 'var(--accent-green)' : 'var(--accent-red)'}`,
            background: 'var(--bg-input)',
            color: allClear ? 'var(--accent-green)' : 'var(--accent-red)',
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            fontWeight: 700,
            letterSpacing: '0.18em',
            textAlign: 'center',
          }}>
            {allClear
              ? 'ALL CLEAR'
              : `${driftingCount} AGENT${driftingCount === 1 ? '' : 'S'} DRIFTING`}
          </div>

          {reports.length === 0 ? (
            <div style={{
              textAlign: 'center', padding: 18,
              fontFamily: 'var(--font-mono)', fontSize: 11,
              color: 'var(--text-dim)', letterSpacing: '0.12em',
              border: '1px dashed var(--border-soft)',
            }}>
              NO DRIFT DATA YET
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th rowSpan={2} style={TH}>Agent</th>
                    <th rowSpan={2} style={{ ...TH, textAlign: 'center', width: 64 }}>Status</th>
                    <th colSpan={3} style={{ ...TH, textAlign: 'center', borderRight: '1px solid var(--border-hair)' }}>
                      Win Rate %
                    </th>
                    <th colSpan={3} style={{ ...TH, textAlign: 'center', borderRight: '1px solid var(--border-hair)' }}>
                      Avg P&amp;L %
                    </th>
                    <th rowSpan={2} style={{ ...TH, textAlign: 'right' }}>Trades</th>
                    <th rowSpan={2} style={{ ...TH, textAlign: 'right' }}>Window</th>
                  </tr>
                  <tr>
                    <th style={{ ...TH, textAlign: 'right' }}>Base</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Now</th>
                    <th style={{ ...TH, textAlign: 'right', borderRight: '1px solid var(--border-hair)' }}>Δ</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Base</th>
                    <th style={{ ...TH, textAlign: 'right' }}>Now</th>
                    <th style={{ ...TH, textAlign: 'right', borderRight: '1px solid var(--border-hair)' }}>Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r, idx) => {
                    const drifting = !!r.is_drifting
                    const statusColor = drifting ? 'var(--accent-red)' : 'var(--accent-green)'
                    const statusText = drifting ? 'DRIFT' : 'OK'

                    const wrBase = num(r.baseline_win_rate)
                    const wrNow = num(r.recent_win_rate ?? r.current_win_rate)
                    const wrDelta = num(r.win_rate_change) ?? (wrBase != null && wrNow != null ? wrNow - wrBase : null)

                    const pnlBase = num(r.baseline_avg_pnl_pct)
                    const pnlNow = num(r.recent_avg_pnl_pct)
                    const pnlDelta = num(r.avg_pnl_change) ?? (pnlBase != null && pnlNow != null ? pnlNow - pnlBase : null)

                    const alerts = alertText(r)

                    return (
                      <React.Fragment key={idx}>
                        <tr style={{ borderTop: '1px solid var(--border-hair)' }}>
                          <td style={{ ...TD, color: 'var(--accent-cyan)', fontWeight: 600 }}>
                            {r.agent_name || '—'}
                          </td>
                          <td style={{ ...TD, textAlign: 'center' }}>
                            <span style={{
                              display: 'inline-block',
                              padding: '1px 8px',
                              border: `1px solid ${statusColor}`,
                              color: statusColor,
                              fontWeight: 700,
                              letterSpacing: '0.12em',
                              fontSize: 10,
                            }}>{statusText}</span>
                          </td>
                          <td style={{ ...TD, textAlign: 'right', color: 'var(--text-secondary)' }}>{fmtPct(wrBase)}</td>
                          <td style={{ ...TD, textAlign: 'right' }}>{fmtPct(wrNow)}</td>
                          <td style={{
                            ...TD, textAlign: 'right',
                            color: deltaColor(wrDelta), fontWeight: 600,
                            borderRight: '1px solid var(--border-hair)',
                          }}>{fmtDelta(wrDelta)}</td>
                          <td style={{ ...TD, textAlign: 'right', color: 'var(--text-secondary)' }}>{fmtPct(pnlBase, 2)}</td>
                          <td style={{ ...TD, textAlign: 'right' }}>{fmtPct(pnlNow, 2)}</td>
                          <td style={{
                            ...TD, textAlign: 'right',
                            color: deltaColor(pnlDelta), fontWeight: 600,
                            borderRight: '1px solid var(--border-hair)',
                          }}>{fmtDelta(pnlDelta, 2)}</td>
                          <td style={{ ...TD, textAlign: 'right', color: 'var(--text-secondary)' }}>
                            {fmtCount(r.total_trades)}
                          </td>
                          <td style={{ ...TD, textAlign: 'right', color: 'var(--text-secondary)' }}>
                            {fmtCount(r.recent_window)}
                          </td>
                        </tr>
                        {alerts && (
                          <tr>
                            <td colSpan={10} style={{
                              padding: '2px 6px 6px 6px',
                              fontFamily: 'var(--font-mono)',
                              fontSize: 10,
                              color: drifting ? 'var(--accent-red)' : 'var(--text-dim)',
                              letterSpacing: '0.05em',
                            }}>
                              ↳ {alerts}
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
