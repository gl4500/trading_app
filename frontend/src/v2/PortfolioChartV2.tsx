import React, { useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import type { Agent } from '../App'

const AGENT_COLORS: Record<string, string> = {
  TechAgent:          '#00d4ff',
  MomentumAgent:      '#a78bfa',
  MeanReversionAgent: '#ffb000',
  SentimentAgent:     '#22c55e',
  ClaudeAgent:        '#ef4444',
  EnsembleAgent:      '#8a8a8a',
  ScannerAgent:       '#ec4899',
}

const STARTING_CAPITAL = 100000

function formatValue(v: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000)     return `$${(v / 1_000).toFixed(1)}K`
  return `$${v.toFixed(0)}`
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: 'var(--bg-panel-hi)',
      border: '1px solid var(--border-soft)',
      padding: 8, fontFamily: 'var(--font-mono)', fontSize: 11,
    }}>
      <div style={{ color: 'var(--text-dim)', marginBottom: 4 }}>{label}</div>
      {payload.map((p: any) => {
        const ret = ((p.value - STARTING_CAPITAL) / STARTING_CAPITAL) * 100
        return (
          <div key={p.name} style={{ display: 'flex', gap: 8, justifyContent: 'space-between' }}>
            <span style={{ color: p.color }}>{p.name}</span>
            <span className="num" style={{ color: 'var(--text-primary)' }}>
              {formatValue(p.value)} ({ret >= 0 ? '+' : ''}{ret.toFixed(2)}%)
            </span>
          </div>
        )
      })}
    </div>
  )
}

interface Props {
  agents: Agent[]
  selectedName: string | null
}

export default function PortfolioChartV2({ agents, selectedName }: Props) {
  const [hidden, setHidden] = useState<Set<string>>(new Set())

  function toggle(name: string) {
    setHidden(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  const visibleAgents = agents.filter(a => !hidden.has(a.name) && a.value_history.length > 0)

  const chartData = useMemo(() => {
    if (visibleAgents.length === 0) return []
    const allTs = new Set<string>()
    visibleAgents.forEach(a => a.value_history.forEach(p => allTs.add(p.timestamp)))
    const sorted = Array.from(allTs).sort()
    const lookups: Record<string, Map<string, number>> = {}
    visibleAgents.forEach(a => {
      lookups[a.name] = new Map(a.value_history.map(p => [p.timestamp, p.value]))
    })
    const last: Record<string, number> = {}
    return sorted.map(ts => {
      const row: Record<string, any> = {
        timestamp: new Date(ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
      }
      visibleAgents.forEach(a => {
        const v = lookups[a.name].get(ts)
        if (v !== undefined) last[a.name] = v
        row[a.name] = last[a.name] ?? STARTING_CAPITAL
      })
      return row
    })
  }, [visibleAgents])

  return (
    <div style={{
      background: 'var(--bg-panel)',
      border: '1px solid var(--border-hair)',
      borderRadius: 'var(--radius-md)',
      padding: 12,
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 10,
      }}>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--accent-amber)', letterSpacing: '0.15em',
        }}>
          PORTFOLIO · PERFORMANCE
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)',
        }}>
          {chartData.length} pts
        </span>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
        {agents.map(a => {
          const color = AGENT_COLORS[a.name] || '#8a8a8a'
          const visible = !hidden.has(a.name)
          const isSel = a.name === selectedName
          return (
            <button
              key={a.name}
              onClick={() => toggle(a.name)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 5,
                padding: '2px 8px',
                background: visible ? `${color}18` : 'transparent',
                border: `1px solid ${visible ? color : 'var(--border-soft)'}`,
                borderRadius: 'var(--radius-sm)',
                color: visible ? color : 'var(--text-dim)',
                fontFamily: 'var(--font-mono)', fontSize: 10,
                letterSpacing: '0.05em',
                cursor: 'pointer',
                outline: isSel ? '1px solid var(--accent-amber)' : 'none',
                outlineOffset: 1,
              }}
            >
              <span style={{
                width: 6, height: 6, borderRadius: '50%',
                background: visible ? color : 'transparent',
                border: visible ? 'none' : '1px solid var(--text-dim)',
              }} />
              {a.name} {a.total_return_pct >= 0 ? '+' : ''}{a.total_return_pct.toFixed(1)}%
            </button>
          )
        })}
      </div>

      {chartData.length > 0 ? (
        <div style={{ height: 'clamp(280px, 42vh, 520px)' }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="var(--border-hair)" />
              <XAxis dataKey="timestamp"
                     tick={{ fontSize: 10, fill: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}
                     axisLine={false} tickLine={false} />
              <YAxis tickFormatter={formatValue}
                     tick={{ fontSize: 10, fill: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}
                     axisLine={false} tickLine={false} width={55} />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={STARTING_CAPITAL} stroke="var(--text-dim)" strokeDasharray="3 4" />
              {visibleAgents.map(a => (
                <Line
                  key={a.name}
                  type="monotone"
                  dataKey={a.name}
                  stroke={AGENT_COLORS[a.name] || '#8a8a8a'}
                  strokeWidth={a.name === selectedName ? 2 : 1.25}
                  dot={false}
                  activeDot={{ r: 3 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div style={{
          height: 'clamp(200px, 30vh, 360px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--text-dim)',
          fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em',
        }}>
          NO DATA · START TRADING TO POPULATE
        </div>
      )}
    </div>
  )
}
