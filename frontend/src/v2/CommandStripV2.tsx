import React from 'react'

interface Props {
  wsConnected: boolean
  isRunning: boolean
  ollamaOnly: boolean
  haltedAgentCount: number
  driftWarningCount: number
  realizedPnlToday: number
  cycleCount: number
}

function Pill({ children, color, dim, title }: { children: React.ReactNode; color?: string; dim?: boolean; title?: string }) {
  return (
    <span title={title} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '3px 10px',
      borderRadius: 'var(--radius-sm)',
      border: `1px solid ${color || 'var(--border-soft)'}`,
      color: dim ? 'var(--text-dim)' : (color || 'var(--text-secondary)'),
      fontFamily: 'var(--font-mono)',
      fontSize: 11,
      letterSpacing: '0.06em',
      whiteSpace: 'nowrap',
    }}>{children}</span>
  )
}

function Dot({ color }: { color: string }) {
  return <span style={{
    display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
    background: color, boxShadow: `0 0 6px ${color}`,
  }} />
}

function formatPnl(v: number) {
  const sign = v >= 0 ? '+' : '-'
  const abs = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return `${sign}$${abs}`
}

export default function CommandStripV2({
  wsConnected, isRunning, ollamaOnly,
  haltedAgentCount, driftWarningCount, realizedPnlToday, cycleCount,
}: Props) {
  const pnlColor = realizedPnlToday >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
      padding: '10px 16px',
      background: 'var(--bg-panel)',
      borderBottom: '1px solid var(--border-hair)',
      position: 'sticky', top: 0, zIndex: 10,
    }}>
      <Pill color={wsConnected ? 'var(--accent-cyan)' : 'var(--text-dim)'}>
        <Dot color={wsConnected ? 'var(--accent-cyan)' : '#444'} />
        {wsConnected ? 'LIVE' : 'OFFLINE'}
      </Pill>

      <Pill color={isRunning ? 'var(--accent-green)' : 'var(--text-dim)'}>
        <Dot color={isRunning ? 'var(--accent-green)' : '#444'} />
        {isRunning ? 'TRADING' : 'PAUSED'}
      </Pill>

      <Pill color="var(--accent-violet)">
        {ollamaOnly ? 'LOCAL · LLAMA' : 'CLOUD · CLAUDE'}
      </Pill>

      <Pill dim>CYCLE {cycleCount}</Pill>

      {haltedAgentCount > 0 && (
        <Pill color="var(--accent-red)">⚠ {haltedAgentCount} HALTED</Pill>
      )}

      {driftWarningCount > 0 && (
        <Pill color="var(--accent-amber)">↯ {driftWarningCount} DRIFT</Pill>
      )}

      <Pill dim title="Regime endpoint not yet exposed">REGIME ·</Pill>
      <Pill dim title="Goal pace endpoint not yet exposed">GOAL ·</Pill>

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--text-dim)', letterSpacing: '0.08em',
        }}>
          PNL TODAY
        </span>
        <span data-testid="pnl-today" className="num" style={{
          fontFamily: 'var(--font-mono)',
          fontVariantNumeric: 'tabular-nums',
          fontSize: 14, fontWeight: 600,
          color: pnlColor,
        }}>
          {formatPnl(realizedPnlToday)}
        </span>
      </div>
    </div>
  )
}
