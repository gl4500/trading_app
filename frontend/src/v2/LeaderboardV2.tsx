import React from 'react'
import type { Agent } from '../App'

interface Props {
  leaderboard: Agent[]
  selected: string | null
  onSelect: (name: string) => void
}

function Sparkline({ values, positive }: { values: number[]; positive: boolean }) {
  if (values.length < 2) return <svg data-testid="sparkline" width={64} height={20} />
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const w = 64, h = 20
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w
    const y = h - ((v - min) / range) * h
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return (
    <svg data-testid="sparkline" width={w} height={h} style={{ display: 'block' }}>
      <polyline
        points={pts}
        fill="none"
        stroke={positive ? 'var(--accent-green)' : 'var(--accent-red)'}
        strokeWidth={1.25}
      />
    </svg>
  )
}

function fmtPct(v: number) {
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

function fmtCurrency(v: number) {
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (Math.abs(v) >= 1_000)     return `$${(v / 1_000).toFixed(1)}K`
  return `$${v.toFixed(0)}`
}

export default function LeaderboardV2({ leaderboard, selected, onSelect }: Props) {
  if (leaderboard.length === 0) {
    return (
      <div style={{
        padding: 24, textAlign: 'center',
        color: 'var(--text-dim)', fontSize: 12, fontFamily: 'var(--font-mono)',
      }}>
        NO AGENTS · START THE COMPETITION
      </div>
    )
  }

  return (
    <div style={{
      background: 'var(--bg-panel)',
      border: '1px solid var(--border-hair)',
      borderRadius: 'var(--radius-md)',
    }}>
      <div style={{
        padding: '10px 12px',
        borderBottom: '1px solid var(--border-hair)',
        fontFamily: 'var(--font-mono)', fontSize: 11,
        color: 'var(--accent-amber)', letterSpacing: '0.15em',
      }}>
        LEADERBOARD · {leaderboard.length}
      </div>

      <div role="list">
        {leaderboard.map((agent, idx) => {
          const isSelected = agent.name === selected
          const positive   = agent.total_return_pct >= 0
          const values     = agent.value_history.map(p => p.value)

          return (
            <button
              key={agent.name}
              type="button"
              onClick={() => onSelect(agent.name)}
              style={{
                display: 'grid',
                gridTemplateColumns: '24px 1fr auto 70px',
                alignItems: 'center', gap: 10,
                width: '100%',
                padding: '10px 12px',
                background: isSelected ? 'var(--bg-panel-hi)' : 'transparent',
                borderLeft: `2px solid ${isSelected ? 'var(--accent-amber)' : 'transparent'}`,
                borderTop: idx === 0 ? 'none' : '1px solid var(--border-hair)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
                textAlign: 'left',
                border: 'none',
                borderLeftStyle: 'solid', borderLeftWidth: 2,
              }}
            >
              <span className="num" style={{
                fontFamily: 'var(--font-mono)',
                color: idx === 0 ? 'var(--accent-amber)' : 'var(--text-dim)',
                fontSize: 13, fontWeight: 600,
              }}>
                {String(idx + 1).padStart(2, '0')}
              </span>

              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{agent.name}</span>
                  {!agent.is_active && (
                    <span style={{
                      fontSize: 9, fontFamily: 'var(--font-mono)',
                      color: 'var(--accent-red)', letterSpacing: '0.1em',
                      border: '1px solid var(--accent-red)', padding: '0 4px',
                      borderRadius: 2,
                    }}>HALTED</span>
                  )}
                </div>
                <div className="num" style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10,
                  color: 'var(--text-dim)',
                  marginTop: 2,
                }}>
                  {fmtCurrency(agent.total_value)} · WR {agent.win_rate.toFixed(0)}% · SR {agent.sharpe_ratio.toFixed(2)} · {agent.total_trades} TR
                </div>
              </div>

              <Sparkline values={values} positive={positive} />

              <span className="num" style={{
                fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600,
                fontVariantNumeric: 'tabular-nums', textAlign: 'right',
                color: positive ? 'var(--accent-green)' : 'var(--accent-red)',
              }}>
                {fmtPct(agent.total_return_pct)}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
