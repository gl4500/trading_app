import React, { useEffect, useState, useCallback } from 'react'
import { useTimezone } from '../context/TimezoneContext'
import { formatTs } from '../utils/time'

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

const NUM: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontVariantNumeric: 'tabular-nums',
  fontSize: 14,
  fontWeight: 600,
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

function regimeColor(state: string | undefined | null): string {
  const s = (state || '').toUpperCase()
  if (s.includes('RISK_ON') || s.includes('BULL') || s === 'OK' || s === 'HEALTHY') return 'var(--accent-green)'
  if (s.includes('RISK_OFF') || s.includes('BEAR') || s === 'POOR') return 'var(--accent-red)'
  if (s.includes('NEUTRAL') || s === 'WARN' || s === 'DEGRADED') return 'var(--accent-amber)'
  return 'var(--text-secondary)'
}

function formatVal(v: any): string {
  if (v == null) return '—'
  if (typeof v === 'number') {
    if (Math.abs(v) < 1 && v !== 0) return v.toFixed(4)
    return v.toLocaleString('en-US', { maximumFractionDigits: 2 })
  }
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE'
  return String(v)
}

const KNOWN_KEYS = new Set([
  'state', 'regime', 'trend', 'volatility', 'breadth', 'score',
  'updated', 'timestamp', 'last_updated',
])

function KvTile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      border: '1px solid var(--border-hair)',
      padding: '4px 8px',
      background: 'var(--bg-input)',
    }}>
      <div style={{ ...NUM, color: color ?? 'var(--text-primary)' }}>{value}</div>
      <div style={LABEL}>{label}</div>
    </div>
  )
}

export default function RegimeV2() {
  const { timeZone } = useTimezone()
  const [regime, setRegime] = useState<Record<string, any> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchRegime = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/cnn-diagnostics`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRegime(data?.regime ?? {})
      setError(null)
    } catch (e: any) {
      setError(e?.message || 'unknown error')
      setRegime(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchRegime()
  }, [fetchRegime])

  const state = regime?.state ?? regime?.regime ?? null
  const trend = regime?.trend ?? null
  const score = regime?.score
  const volatility = regime?.volatility
  const breadth = regime?.breadth
  const updated = regime?.updated ?? regime?.timestamp ?? regime?.last_updated ?? null

  // Other primitive keys
  const otherEntries = regime
    ? Object.entries(regime).filter(([k, v]) =>
        !KNOWN_KEYS.has(k) && (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean')
      )
    : []

  return (
    <div style={PANEL}>
      <div style={HEADER}>
        <span>MARKET REGIME</span>
        <button
          type="button"
          aria-label="Refresh regime"
          onClick={fetchRegime}
          style={REFRESH_BTN}
        >↻ REFRESH</button>
      </div>

      {loading && !regime && !error && (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--text-dim)', letterSpacing: '0.12em',
          border: '1px dashed var(--border-soft)',
        }}>
          LOADING REGIME…
        </div>
      )}

      {error && (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--accent-red)', letterSpacing: '0.12em',
          border: '1px dashed var(--accent-red)',
        }}>
          REGIME UNAVAILABLE — {error}
        </div>
      )}

      {!error && regime && (
        <>
          {/* Top status row: state pill */}
          {state && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <span style={LABEL}>STATE</span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 13,
                fontWeight: 600,
                letterSpacing: '0.15em',
                color: regimeColor(String(state)),
                border: `1px solid ${regimeColor(String(state))}`,
                padding: '2px 10px',
              }}>
                {String(state).toUpperCase()}
              </span>
              {updated && (
                <span style={{ ...LABEL, marginLeft: 'auto' }}>
                  {formatTs(updated, timeZone, {
                    month: 'short', day: 'numeric',
                    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
                  })}
                </span>
              )}
            </div>
          )}

          {/* Primary metric grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 10 }}>
            <KvTile
              label="Score"
              value={formatVal(score)}
              color={typeof score === 'number'
                ? (score >= 0 ? 'var(--accent-green)' : 'var(--accent-red)')
                : undefined}
            />
            <KvTile
              label="Trend"
              value={trend != null ? String(trend).toUpperCase() : '—'}
              color={regimeColor(trend)}
            />
            <KvTile
              label="Volatility"
              value={formatVal(volatility)}
            />
            <KvTile
              label="Breadth"
              value={formatVal(breadth)}
              color={typeof breadth === 'number'
                ? (breadth >= 0.5 ? 'var(--accent-green)' : 'var(--accent-amber)')
                : undefined}
            />
          </div>

          {/* Other primitive key/value pairs */}
          {otherEntries.length > 0 && (
            <div>
              <div style={{ ...LABEL, marginBottom: 4 }}>OTHER</div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
                gap: 4,
              }}>
                {otherEntries.map(([k, v]) => (
                  <div key={k} style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: 8,
                    padding: '3px 6px',
                    border: '1px solid var(--border-hair)',
                    background: 'var(--bg-input)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    fontVariantNumeric: 'tabular-nums',
                  }}>
                    <span style={{ color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{k}</span>
                    <span style={{ color: 'var(--text-primary)' }}>{formatVal(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!state && otherEntries.length === 0 && (
            <div style={{
              textAlign: 'center', padding: 18,
              fontFamily: 'var(--font-mono)', fontSize: 11,
              color: 'var(--text-dim)', letterSpacing: '0.12em',
              border: '1px dashed var(--border-soft)',
            }}>
              NO REGIME DATA YET
            </div>
          )}
        </>
      )}
    </div>
  )
}
