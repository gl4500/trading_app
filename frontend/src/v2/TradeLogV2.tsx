import React, { useMemo, useState } from 'react'
import type { Trade, Agent } from '../App'
import { useTimezone } from '../context/TimezoneContext'
import { formatTs } from '../utils/time'

interface Props {
  trades: Trade[]
  agents: Agent[]
}

const PAGE_SIZE = 20

const AGENT_COLOR: Record<string, string> = {
  TechAgent: 'var(--accent-cyan)',
  MomentumAgent: 'var(--accent-violet)',
  MeanReversionAgent: 'var(--accent-amber)',
  SentimentAgent: 'var(--accent-green)',
  ClaudeAgent: 'var(--accent-red)',
  EnsembleAgent: 'var(--text-secondary)',
  ScannerAgent: 'var(--accent-violet)',
}

const PANEL: React.CSSProperties = {
  background: 'var(--bg-panel)',
  border: '1px solid var(--border-hair)',
  borderRadius: 'var(--radius-sm)',
  padding: '8px 10px',
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

const TH: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.12em',
  color: 'var(--text-dim)',
  textTransform: 'uppercase',
  padding: '4px 6px',
  fontWeight: 500,
  borderBottom: '1px solid var(--border-hair)',
}

const TD: React.CSSProperties = {
  padding: '4px 6px',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontVariantNumeric: 'tabular-nums',
  color: 'var(--text-primary)',
}

function fmtMoney(v: number): string {
  const sign = v >= 0 ? '+' : '-'
  const abs = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return `${sign}$${abs}`
}

function StatTile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      border: '1px solid var(--border-hair)',
      padding: '4px 8px',
      background: 'var(--bg-input)',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 14,
        fontWeight: 600,
        fontVariantNumeric: 'tabular-nums',
        color: color ?? 'var(--text-primary)',
      }}>{value}</div>
      <div style={LABEL}>{label}</div>
    </div>
  )
}

export default function TradeLogV2({ trades }: Props) {
  const { timeZone } = useTimezone()
  const [page, setPage] = useState(0)
  const [filterAgent, setFilterAgent] = useState<string>('all')
  const [filterAction, setFilterAction] = useState<string>('all')

  const agentNames = useMemo(() => {
    const names = new Set(trades.map(t => t.agent_name).filter(Boolean))
    return Array.from(names) as string[]
  }, [trades])

  const filtered = useMemo(() => {
    return trades.filter(t => {
      if (filterAgent !== 'all' && t.agent_name !== filterAgent) return false
      if (filterAction !== 'all' && t.action !== filterAction) return false
      return true
    })
  }, [trades, filterAgent, filterAction])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages - 1)
  const pageData = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)

  const totalBuys = filtered.filter(t => t.action === 'BUY').length
  const totalSells = filtered.filter(t => t.action === 'SELL').length
  const winning = filtered.filter(t => t.action === 'SELL' && (t.pnl ?? 0) > 0).length
  const totalPnl = filtered.reduce((s, t) => s + (t.pnl || 0), 0)

  function handleAgent(v: string) { setPage(0); setFilterAgent(v) }
  function handleAction(v: string) { setPage(0); setFilterAction(v) }

  return (
    <div style={PANEL}>
      <div style={HEADER}>
        <span>TRADE LOG · {filtered.length}</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ ...LABEL, color: 'var(--text-dim)' }}>AGENT</span>
            <select
              aria-label="Agent filter"
              style={SELECT}
              value={filterAgent}
              onChange={e => handleAgent(e.target.value)}
            >
              <option value="all">all</option>
              {agentNames.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ ...LABEL, color: 'var(--text-dim)' }}>ACTION</span>
            <select
              aria-label="Action filter"
              style={SELECT}
              value={filterAction}
              onChange={e => handleAction(e.target.value)}
            >
              <option value="all">all</option>
              <option value="BUY">BUY</option>
              <option value="SELL">SELL</option>
            </select>
          </label>
        </div>
      </div>

      {/* Summary tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
        <StatTile label="Buys" value={String(totalBuys)} color="var(--accent-green)" />
        <StatTile label="Sells" value={String(totalSells)} color="var(--accent-red)" />
        <StatTile
          label="Win Rate"
          value={totalSells > 0 ? `${((winning / totalSells) * 100).toFixed(0)}%` : '—'}
          color="var(--accent-cyan)"
        />
        <StatTile
          label="Total P&L"
          value={fmtMoney(totalPnl)}
          color={totalPnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'}
        />
      </div>

      {/* Table */}
      {pageData.length === 0 ? (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--text-dim)', letterSpacing: '0.12em',
          border: '1px dashed var(--border-soft)',
        }}>
          NO TRADES YET — START THE COMPETITION
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ ...TH, textAlign: 'left'   }}>Time</th>
                <th style={{ ...TH, textAlign: 'left'   }}>Agent</th>
                <th style={{ ...TH, textAlign: 'center' }}>Sym</th>
                <th style={{ ...TH, textAlign: 'center' }}>Action</th>
                <th style={{ ...TH, textAlign: 'right'  }}>Shares</th>
                <th style={{ ...TH, textAlign: 'right'  }}>Price</th>
                <th style={{ ...TH, textAlign: 'right'  }}>P&amp;L</th>
                <th style={{ ...TH, textAlign: 'left'   }}>Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {pageData.map((trade, idx) => {
                const pnlVal = trade.pnl ?? 0
                const pnlColor =
                  trade.action !== 'SELL' ? 'var(--text-dim)' :
                  pnlVal > 0 ? 'var(--accent-green)' :
                  pnlVal < 0 ? 'var(--accent-red)'   :
                               'var(--text-secondary)'
                const actionColor = trade.action === 'BUY' ? 'var(--accent-green)' : 'var(--accent-red)'
                return (
                  <tr key={idx} style={{ borderTop: '1px solid var(--border-hair)' }}>
                    <td style={{ ...TD, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                      {formatTs(trade.timestamp, timeZone, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
                    </td>
                    <td style={{ ...TD, color: AGENT_COLOR[trade.agent_name || ''] || 'var(--text-secondary)' }}>
                      {trade.agent_name || '—'}
                    </td>
                    <td style={{ ...TD, textAlign: 'center', color: 'var(--accent-cyan)', fontWeight: 600 }}>
                      {trade.symbol}
                    </td>
                    <td style={{ ...TD, textAlign: 'center', color: actionColor, fontWeight: 600, letterSpacing: '0.08em' }}>
                      {trade.action}
                    </td>
                    <td style={{ ...TD, textAlign: 'right' }}>{trade.shares.toFixed(2)}</td>
                    <td style={{ ...TD, textAlign: 'right' }}>{trade.price.toFixed(2)}</td>
                    <td style={{ ...TD, textAlign: 'right', color: pnlColor, fontWeight: trade.action === 'SELL' ? 600 : 400 }}>
                      {trade.action === 'SELL' ? fmtMoney(pnlVal) : '—'}
                    </td>
                    <td style={{ ...TD, color: 'var(--text-secondary)', maxWidth: 320 }} title={trade.reasoning}>
                      <span style={{
                        display: '-webkit-box',
                        WebkitLineClamp: 1,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}>
                        {trade.reasoning || '—'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginTop: 8,
          paddingTop: 6,
          borderTop: '1px solid var(--border-hair)',
        }}>
          <span style={LABEL}>
            PAGE {safePage + 1} OF {totalPages} · {filtered.length} TOTAL
          </span>
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              type="button"
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={safePage === 0}
              style={{
                ...SELECT,
                cursor: safePage === 0 ? 'not-allowed' : 'pointer',
                opacity: safePage === 0 ? 0.4 : 1,
              }}
            >‹ PREV</button>
            <button
              type="button"
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={safePage >= totalPages - 1}
              style={{
                ...SELECT,
                cursor: safePage >= totalPages - 1 ? 'not-allowed' : 'pointer',
                opacity: safePage >= totalPages - 1 ? 0.4 : 1,
              }}
            >NEXT ›</button>
          </div>
        </div>
      )}
    </div>
  )
}
