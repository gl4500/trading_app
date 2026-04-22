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
  message?: string
  reason?: string
  [k: string]: any
}

interface DriftResponse {
  reports?: DriftReport[]
  drifting_agents?: number
  all_clear?: boolean
}

const REPORT_KNOWN = new Set(['agent_name', 'is_drifting', 'message', 'reason'])

function detailJson(r: DriftReport): string {
  const numericEntries = Object.entries(r).filter(([k, v]) =>
    !REPORT_KNOWN.has(k) && (typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean')
  )
  if (numericEntries.length === 0) return '—'
  return numericEntries
    .map(([k, v]) => `${k}=${typeof v === 'number' ? v.toFixed(3) : String(v)}`)
    .join(' · ')
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
                    <th style={TH}>Agent</th>
                    <th style={{ ...TH, textAlign: 'center', width: 80 }}>Status</th>
                    <th style={TH}>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r, idx) => {
                    const drifting = !!r.is_drifting
                    const detail = r.message || r.reason || detailJson(r)
                    const statusColor = drifting ? 'var(--accent-red)' : 'var(--accent-green)'
                    const statusText = drifting ? 'DRIFT' : 'OK'
                    return (
                      <tr key={idx} style={{ borderTop: '1px solid var(--border-hair)' }}>
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
                        <td style={{ ...TD, color: 'var(--text-secondary)' }}>
                          {detail}
                        </td>
                      </tr>
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
