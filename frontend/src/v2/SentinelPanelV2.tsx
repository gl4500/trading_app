import React, { useEffect, useState } from 'react'
import { useTimezone } from '../context/TimezoneContext'
import { formatTime } from '../utils/time'

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
  during_session: boolean
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

function categoryColor(cat: string): string {
  switch (cat) {
    case 'policy':       return 'var(--accent-violet)'
    case 'macro':        return 'var(--accent-cyan)'
    case 'geopolitical': return 'var(--accent-amber)'
    case 'regulatory':   return 'var(--accent-red)'
    default:             return 'var(--accent-amber)'
  }
}

function changeCell(pct: number | null): JSX.Element {
  if (pct === null) return <span style={{ ...LABEL }}>PENDING</span>
  const cls = pct > 0 ? 'var(--accent-green)' : pct < 0 ? 'var(--accent-red)' : 'var(--text-secondary)'
  return (
    <span style={{ ...NUM, fontSize: 11, fontWeight: 600, color: cls }}>
      {pct > 0 ? '+' : ''}{pct.toFixed(2)}%
    </span>
  )
}

function minsToHM(mins: number): string {
  if (mins <= 0) return 'NOW'
  const h = Math.floor(mins / 60)
  const m = Math.round(mins % 60)
  return h > 0 ? `${h}H ${m}M` : `${m}M`
}

function CatalystCard({ cat, timeZone }: { cat: Catalyst; timeZone: string }) {
  const ccolor = categoryColor(cat.category)
  return (
    <div style={{
      background: 'var(--bg-panel)',
      border: '1px solid var(--border-hair)',
      borderLeft: `3px solid ${ccolor}`,
      padding: '6px 8px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6, marginBottom: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {cat.symbol && (
            <span style={{ color: 'var(--accent-cyan)', fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: 12 }}>
              {cat.symbol}
            </span>
          )}
          <span style={{
            ...LABEL,
            color: ccolor,
            border: `1px solid ${ccolor}`,
            padding: '0 4px',
          }}>
            {cat.category.toUpperCase()}
          </span>
          <span style={{ ...NUM, fontSize: 11, color: ccolor, fontWeight: 600 }}>
            {'★'.repeat(Math.min(cat.score, 6))}
          </span>
        </div>
        <span style={{ ...LABEL }}>{formatTime(cat.detected_at, timeZone)}</span>
      </div>

      <p style={{
        margin: 0,
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--text-primary)',
        lineHeight: 1.45,
      }}>{cat.headline}</p>

      {cat.summary && (
        <p style={{
          margin: '3px 0 0',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-secondary)',
          lineHeight: 1.4,
        }}>{cat.summary}</p>
      )}

      {(cat.sectors?.length || cat.reason) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
          {cat.sectors?.map(s => (
            <span key={s} style={{
              ...LABEL,
              border: '1px solid var(--border-soft)',
              padding: '0 4px',
              color: 'var(--text-secondary)',
            }}>{s}</span>
          ))}
          {cat.reason && (
            <span style={{ ...LABEL, color: 'var(--text-dim)', fontStyle: 'italic' }}>{cat.reason}</span>
          )}
        </div>
      )}
    </div>
  )
}

function ImpactRow({ snap }: { snap: PriceSnap }) {
  const MOVE_THRESHOLD = 0.05
  const hasMeasurement = snap.change_1h !== null
  const hasMoved = hasMeasurement && Math.abs(snap.change_1h!) >= MOVE_THRESHOLD

  const openLabel = snap.during_session ? '5M' : 'OPEN'

  let status: JSX.Element
  if (!hasMeasurement) {
    status = <span style={{ ...LABEL, color: 'var(--accent-amber)' }}>…</span>
  } else if (hasMoved) {
    status = <span style={{ ...LABEL, color: 'var(--accent-green)' }}>✓</span>
  } else {
    status = <span style={{ ...LABEL, color: 'var(--text-dim)' }}>~</span>
  }

  return (
    <tr style={{ borderTop: '1px solid var(--border-hair)' }}>
      <td style={{ padding: '4px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent-cyan)', fontWeight: 600 }}>
        {snap.symbol}
      </td>
      <td style={{ padding: '4px 6px', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-secondary)', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={snap.headline}>
        {snap.headline}
      </td>
      <td style={{ padding: '4px 6px', textAlign: 'center' }}>
        <span style={{
          ...LABEL,
          color: categoryColor(snap.category),
          border: `1px solid ${categoryColor(snap.category)}`,
          padding: '0 4px',
        }}>
          {snap.category.slice(0, 3).toUpperCase()}
        </span>
      </td>
      <td style={{ ...NUM, fontSize: 11, padding: '4px 6px', textAlign: 'right', color: 'var(--text-secondary)' }}>
        ${snap.price_at.toFixed(2)}
      </td>
      <td style={{ padding: '4px 6px', textAlign: 'center' }}>
        <div style={{ ...LABEL, marginBottom: 2 }}>{openLabel}</div>
        {changeCell(snap.change_open)}
      </td>
      <td style={{ padding: '4px 6px', textAlign: 'center' }}>
        <div style={{ ...LABEL, marginBottom: 2 }}>1H</div>
        {changeCell(snap.change_1h)}
      </td>
      <td style={{ padding: '4px 6px', textAlign: 'center' }}>{status}</td>
    </tr>
  )
}

export default function SentinelPanelV2() {
  const { timeZone } = useTimezone()
  const [sentinel, setSentinel]   = useState<SentinelData | null>(null)
  const [impact, setImpact]       = useState<ImpactData | null>(null)
  const [loading, setLoading]     = useState(true)
  const [lastUpdated, setLU]      = useState<string | null>(null)
  const [activeView, setView]     = useState<'feed' | 'impact'>('feed')
  const [symFilter, setSymFilter] = useState<string>('')

  const fetchAll = async () => {
    try {
      const [sRes, iRes] = await Promise.all([
        fetch(`${API_BASE}/api/sentinel`),
        fetch(`${API_BASE}/api/news-impact`),
      ])
      if (sRes.ok) setSentinel(await sRes.json())
      if (iRes.ok) setImpact(await iRes.json())
      setLU(new Date().toLocaleTimeString(undefined, { timeZone, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }))
    } catch (_) {}
    finally { setLoading(false) }
  }

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 60_000)
    return () => clearInterval(interval)
  }, [])

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
    <div>
      {/* Header */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>SENTINEL · OVERNIGHT INTELLIGENCE</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {lastUpdated && <span style={{ ...LABEL }}>{lastUpdated}</span>}
            <button
              type="button"
              onClick={fetchAll}
              style={{ ...BUTTON, color: 'var(--accent-cyan)' }}
            >↻ REFRESH</button>
          </div>
        </div>

        <div style={{ ...LABEL, marginBottom: 8 }}>
          NEWS · POLICY · EARNINGS · MACRO · GEOPOLITICAL — POLLS EVERY 5 MIN OPEN, 15 MIN OVERNIGHT
        </div>

        {/* Status grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-hair)', padding: '4px 8px' }}>
            <div style={{ ...NUM, fontSize: 13, fontWeight: 600, color: sentinel?.market_is_open ? 'var(--accent-green)' : 'var(--accent-red)' }}>
              {sentinel?.market_status?.toUpperCase() ?? '—'}
            </div>
            <div style={LABEL}>MARKET</div>
          </div>
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-hair)', padding: '4px 8px' }}>
            <div style={{ ...NUM, fontSize: 13, fontWeight: 600, color: 'var(--accent-cyan)' }}>
              {sentinel ? minsToHM(sentinel.minutes_until_open) : '—'}
            </div>
            <div style={LABEL}>NEXT OPEN</div>
          </div>
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-hair)', padding: '4px 8px' }}>
            <div style={{ ...NUM, fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              {formatTime(sentinel?.last_poll ?? null, timeZone)}
            </div>
            <div style={LABEL}>LAST POLL</div>
          </div>
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--border-hair)', padding: '4px 8px' }}>
            <div style={{ ...NUM, fontSize: 13, fontWeight: 600, color: 'var(--accent-amber)' }}>
              {sentinel?.catalyst_count ?? 0}
            </div>
            <div style={LABEL}>CATALYSTS</div>
          </div>
        </div>
      </div>

      {/* View tabs */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={() => setView('feed')}
          style={{
            ...BUTTON,
            color: activeView === 'feed' ? 'var(--bg-base)' : 'var(--accent-amber)',
            background: activeView === 'feed' ? 'var(--accent-amber)' : 'var(--bg-input)',
            borderColor: 'var(--accent-amber)',
          }}
        >CATALYST FEED</button>
        <button
          type="button"
          onClick={() => setView('impact')}
          style={{
            ...BUTTON,
            color: activeView === 'impact' ? 'var(--bg-base)' : 'var(--accent-cyan)',
            background: activeView === 'impact' ? 'var(--accent-cyan)' : 'var(--bg-input)',
            borderColor: 'var(--accent-cyan)',
          }}
        >NEWS → PRICE IMPACT</button>
        {activeView === 'feed' && sortedCategories.map(cat => (
          <span key={cat} style={{
            ...LABEL,
            color: categoryColor(cat),
            border: `1px solid ${categoryColor(cat)}`,
            padding: '0 5px',
          }}>
            {cat} ({byCategory[cat].length})
          </span>
        ))}
      </div>

      {loading ? (
        <div style={{
          ...PANEL,
          borderStyle: 'dashed',
          textAlign: 'center',
          padding: 18,
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-dim)',
          letterSpacing: '0.12em',
        }}>
          LOADING SENTINEL DATA…
        </div>
      ) : activeView === 'feed' ? (
        catalysts.length === 0 ? (
          <div style={{
            ...PANEL,
            borderStyle: 'dashed',
            textAlign: 'center',
            padding: 18,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-dim)',
            letterSpacing: '0.12em',
          }}>
            NO CATALYSTS DETECTED YET — POLLS EVERY 15 MIN WHEN MARKET IS CLOSED
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {sortedCategories.map(cat => (
              <div key={cat} style={PANEL}>
                <div style={HEADER}>
                  <span style={{ color: categoryColor(cat) }}>{cat.toUpperCase()} · {byCategory[cat].length}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {byCategory[cat]
                    .sort((a, b) => b.score - a.score)
                    .map((c, i) => <CatalystCard key={i} cat={c} timeZone={timeZone} />)}
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        <div>
          {(impact?.total ?? 0) === 0 ? (
            <div style={{
              ...PANEL,
              borderStyle: 'dashed',
              textAlign: 'center',
              padding: 18,
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-dim)',
              letterSpacing: '0.12em',
            }}>
              NO PRICE SNAPSHOTS YET — IMPACT DATA BUILDS ONCE CATALYSTS ARE DETECTED
            </div>
          ) : (() => {
            const allSymbols = Array.from(new Set(
              [...(impact?.confirmed ?? []), ...(impact?.pending ?? [])]
                .map(s => s.symbol)
                .filter(Boolean)
            )).sort()

            const confirmed = (impact?.confirmed ?? []).filter(s => !symFilter || s.symbol === symFilter)
            const pending   = (impact?.pending   ?? []).filter(s => !symFilter || s.symbol === symFilter)

            return (
              <>
                {allSymbols.length > 1 && (
                  <div style={{ ...PANEL, display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px' }}>
                    <span style={LABEL}>SYMBOL</span>
                    <select
                      aria-label="Symbol filter"
                      value={symFilter}
                      onChange={e => setSymFilter(e.target.value)}
                      style={{ ...BUTTON, color: 'var(--text-primary)' }}
                    >
                      <option value="">ALL</option>
                      {allSymbols.map(sym => <option key={sym} value={sym}>{sym}</option>)}
                    </select>
                  </div>
                )}

                {confirmed.length > 0 && (
                  <div style={PANEL}>
                    <div style={HEADER}>
                      <span style={{ color: 'var(--accent-green)' }}>CONFIRMED MOVES · {confirmed.length}</span>
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr>
                          <th style={{ ...LABEL, textAlign: 'left',  padding: '4px 6px' }}>SYM</th>
                          <th style={{ ...LABEL, textAlign: 'left',  padding: '4px 6px' }}>CATALYST</th>
                          <th style={{ ...LABEL, textAlign: 'center',padding: '4px 6px' }}>CAT</th>
                          <th style={{ ...LABEL, textAlign: 'right', padding: '4px 6px' }}>PRICE@</th>
                          <th style={{ ...LABEL, textAlign: 'center',padding: '4px 6px' }}>INITIAL</th>
                          <th style={{ ...LABEL, textAlign: 'center',padding: '4px 6px' }}>1H</th>
                          <th style={{ ...LABEL, textAlign: 'center',padding: '4px 6px' }}>STATUS</th>
                        </tr>
                      </thead>
                      <tbody>
                        {confirmed.map((s, i) => <ImpactRow key={i} snap={s} />)}
                      </tbody>
                    </table>
                  </div>
                )}

                {pending.length > 0 && (
                  <div style={PANEL}>
                    <div style={HEADER}>
                      <span style={{ color: 'var(--accent-amber)' }}>PENDING · {pending.length}</span>
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr>
                          <th style={{ ...LABEL, textAlign: 'left',  padding: '4px 6px' }}>SYM</th>
                          <th style={{ ...LABEL, textAlign: 'left',  padding: '4px 6px' }}>CATALYST</th>
                          <th style={{ ...LABEL, textAlign: 'center',padding: '4px 6px' }}>CAT</th>
                          <th style={{ ...LABEL, textAlign: 'right', padding: '4px 6px' }}>PRICE@</th>
                          <th style={{ ...LABEL, textAlign: 'center',padding: '4px 6px' }}>INITIAL</th>
                          <th style={{ ...LABEL, textAlign: 'center',padding: '4px 6px' }}>1H</th>
                          <th style={{ ...LABEL, textAlign: 'center',padding: '4px 6px' }}>STATUS</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pending.map((s, i) => <ImpactRow key={i} snap={s} />)}
                      </tbody>
                    </table>
                  </div>
                )}

                {confirmed.length === 0 && pending.length === 0 && symFilter && (
                  <div style={{
                    ...PANEL,
                    borderStyle: 'dashed',
                    textAlign: 'center',
                    padding: 18,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    color: 'var(--text-dim)',
                    letterSpacing: '0.12em',
                  }}>
                    NO IMPACT DATA FOR {symFilter}
                  </div>
                )}
              </>
            )
          })()}
        </div>
      )}
    </div>
  )
}
