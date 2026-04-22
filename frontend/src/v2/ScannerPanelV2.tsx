import React, { useEffect, useState } from 'react'
import { useTimezone } from '../context/TimezoneContext'
import { formatTime } from '../utils/time'

const API_BASE = ''

interface Candidate {
  symbol: string
  price: number
  pct_change: number
  vol_ratio: number
  momentum_score: number
}

interface Recommendation {
  symbol: string
  action: 'BUY' | 'SELL' | 'WATCH'
  confidence: number
  reasoning: string
  composite_score: number
  price_target?: number
  stop_loss_pct?: number
  catalysts?: string[]
  timestamp: string
}

interface ScanResult {
  status: string
  error?: string
  message?: string
  recommendations: Recommendation[]
  candidates: Candidate[]
  scanned_at?: string
  completed_at?: string
  cache_expires_in?: number
  is_stale?: boolean
  is_scanning?: boolean
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

function actionColor(a: string): string {
  if (a === 'BUY')  return 'var(--accent-green)'
  if (a === 'SELL') return 'var(--accent-red)'
  return 'var(--accent-amber)'
}

function ConfBar({ pct }: { pct: number }) {
  const color = pct >= 70 ? 'var(--accent-green)' : pct >= 45 ? 'var(--accent-amber)' : 'var(--accent-red)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{
        flex: 1,
        height: 4,
        background: 'var(--bg-input)',
        border: '1px solid var(--border-hair)',
        position: 'relative',
        overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute',
          top: 0, bottom: 0, left: 0,
          width: `${Math.min(100, pct)}%`,
          background: color,
        }} />
      </div>
      <span style={{ ...NUM, fontSize: 11, color, fontWeight: 600, width: 30, textAlign: 'right' }}>{pct}%</span>
    </div>
  )
}

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const confPct = Math.round(rec.confidence * 100)
  const score   = rec.composite_score ?? 0
  const acolor  = actionColor(rec.action)

  return (
    <div style={{
      background: 'var(--bg-panel)',
      border: '1px solid var(--border-hair)',
      borderLeft: `3px solid ${acolor}`,
      padding: '8px 10px',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: 'var(--accent-cyan)', fontWeight: 600, fontSize: 14, fontFamily: 'var(--font-mono)' }}>
            {rec.symbol}
          </span>
          <span style={{
            ...LABEL,
            color: acolor,
            border: `1px solid ${acolor}`,
            padding: '0 5px',
            fontSize: 10,
          }}>
            {rec.action}
          </span>
        </div>
        <span style={{
          ...NUM,
          fontSize: 12,
          fontWeight: 600,
          color: score >= 0.15 ? 'var(--accent-green)' : score <= -0.15 ? 'var(--accent-red)' : 'var(--accent-amber)',
        }}>
          {score >= 0 ? '+' : ''}{score.toFixed(2)}
        </span>
      </div>

      {/* Confidence */}
      <div style={{ marginBottom: 6 }}>
        <div style={{ ...LABEL, marginBottom: 2 }}>AI CONFIDENCE</div>
        <ConfBar pct={confPct} />
      </div>

      {/* Reasoning */}
      <p style={{
        margin: 0,
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--text-secondary)',
        lineHeight: 1.45,
        marginBottom: 6,
      }}>{rec.reasoning}</p>

      {/* Catalysts */}
      {rec.catalysts && rec.catalysts.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
          {rec.catalysts.map((c, i) => (
            <span key={i} style={{
              ...LABEL,
              border: '1px solid var(--border-soft)',
              padding: '0 5px',
              color: 'var(--text-secondary)',
              fontSize: 9,
            }}>
              {c}
            </span>
          ))}
        </div>
      )}

      {/* Price target / stop loss */}
      {(rec.price_target != null || rec.stop_loss_pct != null) && (
        <div style={{
          display: 'flex',
          gap: 12,
          paddingTop: 6,
          borderTop: '1px solid var(--border-hair)',
        }}>
          {rec.price_target != null && (
            <div>
              <span style={{ ...LABEL }}>TARGET </span>
              <span style={{ ...NUM, fontSize: 11, color: 'var(--accent-cyan)', fontWeight: 600 }}>
                ${rec.price_target.toFixed(2)}
              </span>
            </div>
          )}
          {rec.stop_loss_pct != null && (
            <div>
              <span style={{ ...LABEL }}>STOP </span>
              <span style={{ ...NUM, fontSize: 11, color: 'var(--accent-red)', fontWeight: 600 }}>
                -{rec.stop_loss_pct}%
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function ScannerPanelV2() {
  const { timeZone } = useTimezone()
  const [result, setResult]     = useState<ScanResult | null>(null)
  const [, setLoading]          = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [showAll, setShowAll]   = useState(false)

  const fetchCached = async (quiet = false) => {
    try {
      if (!quiet) setLoading(true)
      const res = await fetch(`${API_BASE}/api/scanner`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: ScanResult = await res.json()
      setResult(data)
      setScanning(!!data.is_scanning)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      if (!quiet) setLoading(false)
    }
  }

  const runScan = async () => {
    try {
      setScanning(true)
      setError(null)
      const res = await fetch(`${API_BASE}/api/scanner/run`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: ScanResult = await res.json()
      setResult(data)
      setScanning(!!data.is_scanning)
    } catch (e: any) {
      setError(e.message)
      setScanning(false)
    }
  }

  useEffect(() => { fetchCached() }, [])

  useEffect(() => {
    if (!scanning) return
    const id = setInterval(() => fetchCached(true), 3000)
    return () => clearInterval(id)
  }, [scanning])

  const recs    = result?.recommendations ?? []
  const cands   = result?.candidates ?? []
  const buys    = recs.filter(r => r.action === 'BUY').length
  const sells   = recs.filter(r => r.action === 'SELL').length
  const watches = recs.filter(r => r.action === 'WATCH').length

  const scannedTime = result?.scanned_at ? formatTime(result.scanned_at, timeZone) : null

  return (
    <div>
      {/* Header */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>SCANNER · AGENTIC STOCK SCANNER</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {recs.length > 0 && (
              <>
                {buys    > 0 && <span style={{ ...LABEL, color: 'var(--accent-green)', border: '1px solid var(--accent-green)', padding: '0 5px' }}>{buys} BUY</span>}
                {sells   > 0 && <span style={{ ...LABEL, color: 'var(--accent-red)',   border: '1px solid var(--accent-red)',   padding: '0 5px' }}>{sells} SELL</span>}
                {watches > 0 && <span style={{ ...LABEL, color: 'var(--accent-amber)', border: '1px solid var(--accent-amber)', padding: '0 5px' }}>{watches} WATCH</span>}
              </>
            )}
            {scannedTime && (
              <span style={{ ...LABEL }}>LAST {scannedTime}</span>
            )}
            <button
              type="button"
              onClick={runScan}
              disabled={scanning}
              style={{
                ...BUTTON,
                color: scanning ? 'var(--text-dim)' : 'var(--accent-violet)',
                borderColor: scanning ? 'var(--border-hair)' : 'var(--accent-violet)',
                cursor: scanning ? 'not-allowed' : 'pointer',
              }}
            >
              {scanning ? 'SCANNING…' : '⟁ RUN SCAN'}
            </button>
          </div>
        </div>

        <div style={{ ...LABEL, marginBottom: 0 }}>
          CLAUDE SCANS ~160 STOCKS · HIGH-CONVICTION OPPORTUNITIES
        </div>
      </div>

      {scanning && (
        <div style={{
          ...PANEL,
          borderColor: 'var(--accent-violet)',
          textAlign: 'center',
          padding: 18,
        }}>
          <div style={{ ...LABEL, color: 'var(--accent-violet)', marginBottom: 4 }}>
            ⟁ AGENTS SCANNING THE MARKET
          </div>
          <div style={{ ...LABEL, color: 'var(--text-dim)' }}>
            PRE-SCREEN ~160 · DEEP-DIVE CANDIDATES · 30–90 SECONDS
          </div>
        </div>
      )}

      {!scanning && result?.is_stale && (
        <div style={{
          ...PANEL,
          borderColor: 'var(--accent-amber)',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--accent-amber)',
          letterSpacing: '0.12em',
        }}>
          ⚠ STALE — RUN A NEW SCAN TO REFRESH
        </div>
      )}

      {error && !scanning && (
        <div style={{
          ...PANEL,
          borderColor: 'var(--accent-red)',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--accent-red)',
        }}>
          ERROR: {error}
        </div>
      )}

      {!scanning && (result?.status === 'no_scan' || result?.status === 'scanning') && (
        <div style={{
          ...PANEL,
          borderStyle: 'dashed',
          textAlign: 'center',
          padding: 20,
          fontFamily: 'var(--font-mono)',
          letterSpacing: '0.12em',
          color: 'var(--text-dim)',
        }}>
          <div style={{ fontSize: 13, marginBottom: 4 }}>⟁ NO SCAN RESULTS YET</div>
          <div style={{ fontSize: 11 }}>AUTO-RUNS EVERY 30 MIN DURING MARKET HOURS · CLICK RUN SCAN</div>
        </div>
      )}

      {!scanning && recs.length > 0 && (
        <div style={PANEL}>
          <div style={HEADER}>
            <span>RECOMMENDATIONS · {recs.length}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 8 }}>
            {recs
              .sort((a, b) => b.confidence - a.confidence)
              .map(rec => <RecommendationCard key={rec.symbol} rec={rec} />)}
          </div>
        </div>
      )}

      {!scanning && recs.length === 0 && result?.status === 'ok' && (
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
          NO HIGH-CONVICTION OPPORTUNITIES THIS SCAN
        </div>
      )}

      {/* Pre-screen candidates */}
      {!scanning && cands.length > 0 && (
        <div style={PANEL}>
          <button
            type="button"
            onClick={() => setShowAll(s => !s)}
            style={{
              width: '100%',
              background: 'transparent',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span style={{ ...HEADER, marginBottom: 0, paddingBottom: 0, borderBottom: 'none', flex: 1 }}>
              <span>PRE-SCREEN MOMENTUM CANDIDATES · {cands.length}</span>
              <span style={{ color: 'var(--accent-cyan)' }}>{showAll ? '▲' : '▼'}</span>
            </span>
          </button>
          {showAll && (
            <div style={{ marginTop: 8, borderTop: '1px solid var(--border-hair)', paddingTop: 6 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{ ...LABEL, textAlign: 'right', padding: '4px 6px' }}>#</th>
                    <th style={{ ...LABEL, textAlign: 'left',  padding: '4px 6px' }}>SYM</th>
                    <th style={{ ...LABEL, textAlign: 'right', padding: '4px 6px' }}>PRICE</th>
                    <th style={{ ...LABEL, textAlign: 'right', padding: '4px 6px' }}>%CHG</th>
                    <th style={{ ...LABEL, textAlign: 'right', padding: '4px 6px' }}>VOL×</th>
                  </tr>
                </thead>
                <tbody>
                  {cands.map((c, i) => {
                    const up = c.pct_change >= 0
                    return (
                      <tr key={c.symbol} style={{ borderTop: '1px solid var(--border-hair)' }}>
                        <td style={{ ...NUM, fontSize: 11, padding: '4px 6px', textAlign: 'right', color: 'var(--text-dim)' }}>{i + 1}</td>
                        <td style={{ padding: '4px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent-cyan)', fontWeight: 600 }}>{c.symbol}</td>
                        <td style={{ ...NUM, fontSize: 11, padding: '4px 6px', textAlign: 'right', color: 'var(--text-secondary)' }}>${c.price.toFixed(2)}</td>
                        <td style={{ ...NUM, fontSize: 11, padding: '4px 6px', textAlign: 'right', fontWeight: 600, color: up ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                          {up ? '+' : ''}{c.pct_change.toFixed(2)}%
                        </td>
                        <td style={{ ...NUM, fontSize: 11, padding: '4px 6px', textAlign: 'right', color: 'var(--text-dim)' }}>×{c.vol_ratio.toFixed(1)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
