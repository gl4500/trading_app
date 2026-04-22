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

interface CnnDiag {
  trained?: boolean
  device?: string
  n_channels?: number
  n_train?: number
  n_val?: number
  final_train_mse?: number
  final_val_mse?: number
  overfit_ratio?: number
  diagnosis?: string
  walk_forward_efficiency?: number
  wfe_status?: string
  train_loss_curve?: number[]
  val_loss_curve?: number[]
  learned_weights?: Record<string, number>
  weight_delta?: number | Record<string, number>
  last_trained?: string | null
  [k: string]: any
}

function diagnosisColor(d: string | undefined): string {
  switch ((d || '').toUpperCase()) {
    case 'OK':
      return 'var(--accent-green)'
    case 'OVERFIT':
    case 'OVERFIT_MEMORIZING':
      return 'var(--accent-red)'
    case 'UNDERFIT':
      return 'var(--accent-amber)'
    case 'UNTRAINED':
    default:
      return 'var(--text-dim)'
  }
}

function wfeColor(s: string | undefined): string {
  switch ((s || '').toUpperCase()) {
    case 'HEALTHY':
      return 'var(--accent-green)'
    case 'DEGRADED':
      return 'var(--accent-amber)'
    case 'POOR':
      return 'var(--accent-red)'
    case 'UNTRAINED':
    default:
      return 'var(--text-dim)'
  }
}

function fmtNum(v: number | undefined | null, decimals = 4): string {
  if (v == null || Number.isNaN(v)) return '—'
  if (Math.abs(v) >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 0 })
  return v.toFixed(decimals)
}

function StatusPill({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'flex-start',
      gap: 4,
      padding: '6px 12px',
      border: `1px solid ${color}`,
      background: 'var(--bg-input)',
      flex: 1,
    }}>
      <span style={{ ...LABEL, color: 'var(--text-dim)' }}>{label}</span>
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 16,
        fontWeight: 700,
        letterSpacing: '0.18em',
        color,
      }}>{value}</span>
    </div>
  )
}

function MetricTile({ label, value, color }: { label: string; value: string; color?: string }) {
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

function Sparkline({ data, color, width = 120, height = 30 }: {
  data: number[]; color: string; width?: number; height?: number
}) {
  if (!data || data.length < 2) {
    return (
      <div style={{
        width, height,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        ...LABEL,
        border: '1px dashed var(--border-soft)',
      }}>
        NO DATA
      </div>
    )
  }
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const stepX = width / (data.length - 1)
  const points = data
    .map((v, i) => `${(i * stepX).toFixed(2)},${(height - ((v - min) / range) * height).toFixed(2)}`)
    .join(' ')
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: 'block' }}
    >
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
      />
    </svg>
  )
}

function SparkCard({ title, data, color }: { title: string; data: number[]; color: string }) {
  const last = data && data.length > 0 ? data[data.length - 1] : null
  return (
    <div style={{
      border: '1px solid var(--border-hair)',
      background: 'var(--bg-input)',
      padding: '4px 8px',
      flex: 1,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ ...LABEL, color }}>{title}</span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          fontVariantNumeric: 'tabular-nums',
          color: 'var(--text-primary)',
        }}>
          {last != null ? last.toFixed(4) : '—'}
        </span>
      </div>
      <Sparkline data={data || []} color={color} width={160} height={32} />
    </div>
  )
}

export default function CNNDiagnosticsV2() {
  const { timeZone } = useTimezone()
  const [diag, setDiag] = useState<CnnDiag | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchDiag = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/cnn-diagnostics`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setDiag(data || {})
      setError(null)
    } catch (e: any) {
      setError(e?.message || 'unknown error')
      setDiag(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDiag()
  }, [fetchDiag])

  const diagnosis = diag?.diagnosis ?? 'UNTRAINED'
  const wfeStatus = diag?.wfe_status ?? 'UNTRAINED'
  const trainCurve = diag?.train_loss_curve ?? []
  const valCurve = diag?.val_loss_curve ?? []
  const learnedWeights = diag?.learned_weights ?? {}
  const weightEntries = Object.entries(learnedWeights)

  return (
    <div style={PANEL}>
      <div style={HEADER}>
        <span>CNN DIAGNOSTICS</span>
        <button
          type="button"
          aria-label="Refresh CNN diagnostics"
          onClick={fetchDiag}
          style={REFRESH_BTN}
        >↻ REFRESH</button>
      </div>

      {loading && !diag && !error && (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--text-dim)', letterSpacing: '0.12em',
          border: '1px dashed var(--border-soft)',
        }}>
          LOADING DIAGNOSTICS…
        </div>
      )}

      {error && (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--accent-red)', letterSpacing: '0.12em',
          border: '1px dashed var(--accent-red)',
        }}>
          DIAGNOSTICS UNAVAILABLE — {error}
        </div>
      )}

      {!error && diag && (
        <>
          {/* Status pills */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <StatusPill
              label="DIAGNOSIS"
              value={String(diagnosis).toUpperCase()}
              color={diagnosisColor(diagnosis)}
            />
            <StatusPill
              label="WFE"
              value={String(wfeStatus).toUpperCase()}
              color={wfeColor(wfeStatus)}
            />
          </div>

          {/* Primary metric grid (5-up) */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6, marginBottom: 8 }}>
            <MetricTile label="N CHANNELS"  value={fmtNum(diag.n_channels, 0)} />
            <MetricTile label="N TRAIN"     value={fmtNum(diag.n_train, 0)} />
            <MetricTile label="N VAL"       value={fmtNum(diag.n_val, 0)} />
            <MetricTile label="TRAIN MSE"   value={fmtNum(diag.final_train_mse, 4)} />
            <MetricTile label="VAL MSE"     value={fmtNum(diag.final_val_mse, 4)} />
          </div>

          {/* Secondary metric row */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 10 }}>
            <MetricTile
              label="OVERFIT RATIO"
              value={fmtNum(diag.overfit_ratio, 2)}
              color={typeof diag.overfit_ratio === 'number' && diag.overfit_ratio > 2
                ? 'var(--accent-red)'
                : 'var(--text-primary)'}
            />
            <MetricTile
              label="WFE"
              value={fmtNum(diag.walk_forward_efficiency, 3)}
            />
            <MetricTile
              label="DEVICE"
              value={(diag.device || '—').toUpperCase()}
              color="var(--accent-cyan)"
            />
            <MetricTile
              label="LAST TRAINED"
              value={diag.last_trained
                ? formatTs(diag.last_trained, timeZone, {
                    month: 'short', day: 'numeric',
                    hour: '2-digit', minute: '2-digit', hour12: false,
                  })
                : '—'}
            />
          </div>

          {/* Loss sparkline cards */}
          {(trainCurve.length > 0 || valCurve.length > 0) ? (
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              <SparkCard title="TRAIN LOSS" data={trainCurve} color="var(--accent-cyan)" />
              <SparkCard title="VAL LOSS"   data={valCurve}   color="var(--accent-amber)" />
            </div>
          ) : (
            <div style={{
              textAlign: 'center', padding: 12, marginBottom: 10,
              fontFamily: 'var(--font-mono)', fontSize: 11,
              color: 'var(--text-dim)', letterSpacing: '0.12em',
              border: '1px dashed var(--border-soft)',
            }}>
              NO LOSS DATA YET
            </div>
          )}

          {/* Learned weights */}
          {weightEntries.length > 0 && (
            <div>
              <div style={{ ...LABEL, marginBottom: 4 }}>LEARNED WEIGHTS</div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
                gap: 4,
              }}>
                {weightEntries.map(([k, v]) => (
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
                    <span style={{ color: 'var(--text-primary)' }}>
                      {typeof v === 'number' ? v.toFixed(4) : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
