import React, { useState } from 'react'
import type { Agent } from '../App'

interface Props {
  agent: Agent
  prices: Record<string, number>
}

function fmtMoney(v: number): string {
  const sign = v >= 0 ? '+' : '-'
  const abs = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return `${sign}$${abs}`
}

function fmtPct(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function colorFor(v: number): string {
  return v >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'
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

function MetricCell({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div>
      <div style={{ ...NUM, color: color ?? 'var(--text-primary)' }}>{value}</div>
      <div style={LABEL}>{label}</div>
      {sub && (
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-secondary)',
          fontVariantNumeric: 'tabular-nums',
          marginTop: 2,
        }}>{sub}</div>
      )}
    </div>
  )
}

export default function AgentCardV2({ agent }: Props) {
  const [showAllSignals, setShowAllSignals] = useState(false)

  const cashPct = agent.total_value > 0 ? (agent.cash / agent.total_value) * 100 : 100
  const investedPct = 100 - cashPct
  const unrealized = (agent.positions || []).reduce((s, p) => s + p.unrealized_pnl, 0)
  const realized = agent.total_return - unrealized

  const signals = Object.entries(agent.last_signals || {})
  const displaySignals = showAllSignals ? signals : signals.slice(0, 3)

  return (
    <div>
      {/* Header panel: name + status + metrics */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>{agent.name} · <span style={{ color: 'var(--text-secondary)' }}>{agent.strategy || '—'}</span></span>
          <span style={{
            fontSize: 10,
            color: agent.is_active ? 'var(--accent-green)' : 'var(--accent-red)',
            border: `1px solid ${agent.is_active ? 'var(--accent-green)' : 'var(--accent-red)'}`,
            padding: '1px 6px',
            letterSpacing: '0.12em',
          }}>
            {agent.is_active ? 'ACTIVE' : 'HALTED'}
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 10 }}>
          <MetricCell
            label="Total Return"
            value={fmtPct(agent.total_return_pct)}
            sub={fmtMoney(agent.total_return)}
            color={colorFor(agent.total_return_pct)}
          />
          <MetricCell
            label="Unrealized"
            value={fmtMoney(unrealized)}
            color={colorFor(unrealized)}
          />
          <MetricCell
            label="Realized"
            value={fmtMoney(realized)}
            color={colorFor(realized)}
          />
          <MetricCell
            label="Win Rate"
            value={`${agent.win_rate.toFixed(1)}%`}
            sub={`${agent.total_trades} trades`}
            color={agent.win_rate >= 50 ? 'var(--accent-green)' : 'var(--accent-red)'}
          />
          <MetricCell
            label="Sharpe"
            value={agent.sharpe_ratio.toFixed(3)}
            sub={`MaxDD ${agent.max_drawdown.toFixed(1)}%`}
            color={agent.sharpe_ratio > 0 ? 'var(--accent-cyan)' : 'var(--text-secondary)'}
          />
        </div>

        {/* Cash / invested allocation bar */}
        <div>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            ...LABEL,
            marginBottom: 4,
          }}>
            <span>CASH ${agent.cash.toFixed(0)} · {cashPct.toFixed(1)}%</span>
            <span>INV ${agent.position_value.toFixed(0)} · {investedPct.toFixed(1)}%</span>
          </div>
          <div style={{
            height: 4,
            background: 'var(--bg-input)',
            border: '1px solid var(--border-hair)',
            position: 'relative',
            overflow: 'hidden',
          }}>
            <div style={{
              position: 'absolute',
              left: 0, top: 0, bottom: 0,
              width: `${investedPct}%`,
              background: 'var(--accent-cyan)',
            }} />
          </div>
        </div>
      </div>

      {/* Positions table */}
      {agent.positions && agent.positions.length > 0 && (
        <div style={PANEL}>
          <div style={HEADER}>
            <span>POSITIONS · {agent.positions.length}</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
              <thead>
                <tr style={{ color: 'var(--text-dim)', fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
                  <th style={{ textAlign: 'left',  padding: '4px 6px' }}>Sym</th>
                  <th style={{ textAlign: 'right', padding: '4px 6px' }}>Shares</th>
                  <th style={{ textAlign: 'right', padding: '4px 6px' }}>Avg</th>
                  <th style={{ textAlign: 'right', padding: '4px 6px' }}>Cur</th>
                  <th style={{ textAlign: 'right', padding: '4px 6px' }}>Value</th>
                  <th style={{ textAlign: 'right', padding: '4px 6px' }}>P&amp;L</th>
                  <th style={{ textAlign: 'right', padding: '4px 6px' }}>P&amp;L %</th>
                </tr>
              </thead>
              <tbody>
                {agent.positions.map(p => {
                  const pnlColor = colorFor(p.unrealized_pnl)
                  return (
                    <tr key={p.symbol} style={{ borderTop: '1px solid var(--border-hair)' }}>
                      <td style={{ padding: '4px 6px', color: 'var(--accent-cyan)', fontWeight: 600 }}>{p.symbol}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: 'var(--text-primary)' }}>{p.shares.toFixed(2)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: 'var(--text-secondary)' }}>{p.avg_cost.toFixed(2)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: 'var(--text-primary)' }}>{p.current_price.toFixed(2)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: 'var(--text-primary)' }}>{p.current_value.toFixed(2)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: pnlColor, fontWeight: 600 }}>{fmtMoney(p.unrealized_pnl)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: pnlColor, fontWeight: 600 }}>{fmtPct(p.unrealized_pnl_pct)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Last AI decisions */}
      {signals.length > 0 && (
        <div style={PANEL}>
          <div style={HEADER}>
            <span>LAST DECISIONS · {signals.length}</span>
            {signals.length > 3 && (
              <button
                type="button"
                onClick={() => setShowAllSignals(!showAllSignals)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--accent-cyan)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  letterSpacing: '0.12em',
                  cursor: 'pointer',
                }}
              >
                {showAllSignals ? '[ COLLAPSE ]' : `[ SHOW ALL ]`}
              </button>
            )}
          </div>
          <div>
            {displaySignals.map(([symbol, sig]) => {
              const actionColor =
                sig.action === 'BUY'  ? 'var(--accent-green)' :
                sig.action === 'SELL' ? 'var(--accent-red)'   :
                                        'var(--text-dim)'
              return (
                <div key={symbol} style={{
                  borderTop: '1px solid var(--border-hair)',
                  padding: '6px 0',
                }}>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    marginBottom: 3,
                  }}>
                    <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>{symbol}</span>
                    <span style={{ color: actionColor, fontWeight: 600, letterSpacing: '0.1em' }}>{sig.action}</span>
                    <span style={{ color: 'var(--text-dim)', marginLeft: 'auto' }}>
                      CONF {(sig.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p style={{
                    margin: 0,
                    fontSize: 11,
                    color: 'var(--text-secondary)',
                    lineHeight: 1.45,
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}>{sig.reasoning}</p>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {signals.length === 0 && agent.name === 'ScannerAgent' && (
        <div style={{ ...PANEL, borderStyle: 'dashed', textAlign: 'center', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11, padding: 16 }}>
          ⟁ NO SIGNALS YET — RUN A SCAN FIRST
        </div>
      )}
    </div>
  )
}
