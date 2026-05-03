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

const SELECT: React.CSSProperties = {
  background: 'var(--bg-input)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--text-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  padding: '2px 6px',
  letterSpacing: '0.05em',
}

interface TaxResponse {
  year?: number
  short_term_gain?: number
  short_term_loss?: number
  short_term_net?: number
  long_term_gain?: number
  long_term_loss?: number
  long_term_net?: number
  wash_sale_count?: number
  quarterly_net?: Record<string, number> | number[]
  total_net?: number
  [k: string]: any
}

function fmtMoney(v: number | undefined | null): string {
  if (v == null || Number.isNaN(v)) return '—'
  const sign = v >= 0 ? '+' : '-'
  const abs = Math.abs(v).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return `${sign}$${abs}`
}

function netColor(v: number | undefined | null): string {
  if (v == null) return 'var(--text-secondary)'
  return v >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'
}

function CategoryCard({ title, gain, loss, net }: {
  title: string
  gain: number | undefined
  loss: number | undefined
  net: number | undefined
}) {
  return (
    <div style={{
      border: '1px solid var(--border-hair)',
      background: 'var(--bg-input)',
      padding: '8px 10px',
    }}>
      <div style={{ ...LABEL, marginBottom: 6 }}>{title}</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
        <div>
          <div style={{ ...NUM, color: 'var(--accent-green)' }}>{fmtMoney(gain)}</div>
          <div style={LABEL}>GAIN</div>
        </div>
        <div>
          <div style={{ ...NUM, color: 'var(--accent-red)' }}>{fmtMoney(loss)}</div>
          <div style={LABEL}>LOSS</div>
        </div>
        <div>
          <div style={{ ...NUM, color: netColor(net) }}>{fmtMoney(net)}</div>
          <div style={LABEL}>NET</div>
        </div>
      </div>
    </div>
  )
}

function QuarterTile({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div style={{
      border: '1px solid var(--border-hair)',
      background: 'var(--bg-input)',
      padding: '4px 8px',
      textAlign: 'center',
    }}>
      <div style={{ ...NUM, fontSize: 12, color: netColor(value) }}>{fmtMoney(value)}</div>
      <div style={{ ...LABEL, marginTop: 2 }}>{label}</div>
    </div>
  )
}

export default function TaxV2() {
  const currentYear = new Date().getFullYear()
  const [year, setYear] = useState<number>(currentYear)
  const [data, setData] = useState<TaxResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)

  const fetchTax = useCallback(async (y: number) => {
    setLoading(true)
    setUnavailable(false)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/tax/estimate?year=${y}`)
      if (res.status === 503) {
        let detailErr = 'alpaca_unavailable'
        try {
          const body = await res.json()
          detailErr = body?.detail?.error ?? detailErr
        } catch { /* ignore */ }
        if (detailErr === 'alpaca_unavailable') {
          setUnavailable(true)
        } else {
          setError(detailErr)
        }
        setData(null)
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = await res.json()
      setData(body || {})
    } catch (e: any) {
      setError(e?.message || 'unknown error')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTax(year)
  }, [year, fetchTax])

  const yearOptions = [currentYear, currentYear - 1, currentYear - 2]

  // Normalise quarterly_net into Q1..Q4
  let q1: number | undefined, q2: number | undefined, q3: number | undefined, q4: number | undefined
  const qn = data?.quarterly_net
  if (Array.isArray(qn)) {
    q1 = qn[0]; q2 = qn[1]; q3 = qn[2]; q4 = qn[3]
  } else if (qn && typeof qn === 'object') {
    q1 = qn.Q1 ?? qn.q1
    q2 = qn.Q2 ?? qn.q2
    q3 = qn.Q3 ?? qn.q3
    q4 = qn.Q4 ?? qn.q4
  }

  const washCount = data?.wash_sale_count ?? 0

  return (
    <div style={PANEL}>
      <div style={HEADER}>
        <span>TAX ESTIMATE · {year}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ ...LABEL, color: 'var(--text-dim)' }}>YEAR</span>
            <select
              aria-label="Year"
              value={year}
              onChange={e => setYear(parseInt(e.target.value, 10))}
              style={SELECT}
            >
              {yearOptions.map(y => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            aria-label="Refresh tax"
            onClick={() => fetchTax(year)}
            style={REFRESH_BTN}
          >↻ REFRESH</button>
        </div>
      </div>

      {loading && !data && !error && !unavailable && (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--text-dim)', letterSpacing: '0.12em',
          border: '1px dashed var(--border-soft)',
        }}>
          LOADING TAX ESTIMATE…
        </div>
      )}

      {unavailable && (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--accent-amber)', letterSpacing: '0.15em',
          border: '1px dashed var(--accent-amber)',
        }}>
          ALPACA UNAVAILABLE — TRADES NOT AVAILABLE
        </div>
      )}

      {error && (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--accent-red)', letterSpacing: '0.12em',
          border: '1px dashed var(--accent-red)',
        }}>
          TAX UNAVAILABLE — {error}
        </div>
      )}

      {!error && !unavailable && data && (
        <>
          {/* Short / Long term cards */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            <CategoryCard
              title="SHORT-TERM"
              gain={data.short_term_gain}
              loss={data.short_term_loss}
              net={data.short_term_net}
            />
            <CategoryCard
              title="LONG-TERM"
              gain={data.long_term_gain}
              loss={data.long_term_loss}
              net={data.long_term_net}
            />
          </div>

          {/* Wash sales tile + total net (full width) */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 8, marginBottom: 8 }}>
            <div style={{
              border: '1px solid var(--border-hair)',
              background: 'var(--bg-input)',
              padding: '8px 10px',
              textAlign: 'center',
            }}>
              <div style={{
                ...NUM,
                fontSize: 18,
                color: washCount > 0 ? 'var(--accent-amber)' : 'var(--text-dim)',
              }}>
                {washCount}
              </div>
              <div style={{ ...LABEL, marginTop: 2 }}>WASH SALES</div>
            </div>
            <div style={{
              border: `1px solid ${netColor(data.total_net)}`,
              background: 'var(--bg-input)',
              padding: '8px 10px',
              textAlign: 'center',
            }}>
              <div style={{
                ...NUM,
                fontSize: 22,
                color: netColor(data.total_net),
              }}>
                {fmtMoney(data.total_net)}
              </div>
              <div style={{ ...LABEL, marginTop: 2 }}>TOTAL NET</div>
            </div>
          </div>

          {/* Quarterly net */}
          <div>
            <div style={{ ...LABEL, marginBottom: 4 }}>QUARTERLY NET</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
              <QuarterTile label="Q1" value={q1} />
              <QuarterTile label="Q2" value={q2} />
              <QuarterTile label="Q3" value={q3} />
              <QuarterTile label="Q4" value={q4} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
