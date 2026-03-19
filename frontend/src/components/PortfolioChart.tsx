import React, { useState, useMemo } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { Agent } from '../App'

interface PortfolioChartProps {
  agents: Agent[]
  selectedAgentName: string | null
}

const AGENT_COLORS: Record<string, string> = {
  TechAgent: '#3b82f6',           // blue
  MomentumAgent: '#a855f7',      // purple
  MeanReversionAgent: '#eab308', // yellow
  SentimentAgent: '#22c55e',     // green
  ClaudeAgent: '#ef4444',        // red
  EnsembleAgent: '#94a3b8',      // slate
  ScannerAgent: '#8b5cf6',       // violet
}

const STARTING_CAPITAL = 100000

function formatValue(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return `$${value.toFixed(0)}`
}

function formatTime(timestamp: string): string {
  try {
    const d = new Date(timestamp)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return timestamp
  }
}

interface TooltipProps {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string }>
  label?: string
}

function CustomTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null

  return (
    <div className="bg-gray-800 border border-gray-600 rounded-lg p-3 shadow-xl text-xs">
      <p className="text-gray-400 mb-2">{label}</p>
      {payload.map(entry => {
        const returnPct = ((entry.value - STARTING_CAPITAL) / STARTING_CAPITAL) * 100
        return (
          <div key={entry.name} className="flex items-center justify-between gap-4 mb-1">
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
              <span className="text-gray-300">{entry.name}</span>
            </div>
            <div className="text-right">
              <span className="font-medium text-white">{formatValue(entry.value)}</span>
              <span className={`ml-2 ${returnPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ({returnPct >= 0 ? '+' : ''}{returnPct.toFixed(2)}%)
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function PortfolioChart({ agents, selectedAgentName }: PortfolioChartProps) {
  const [visibleAgents, setVisibleAgents] = useState<Set<string>>(
    new Set(Object.keys(AGENT_COLORS))
  )

  function toggleAgent(name: string) {
    setVisibleAgents(prev => {
      const next = new Set(prev)
      if (next.has(name)) {
        if (next.size > 1) next.delete(name) // keep at least one
      } else {
        next.add(name)
      }
      return next
    })
  }

  // Merge all agents' value histories into a unified timeline
  const chartData = useMemo(() => {
    const agentsWithHistory = agents.filter(
      a => a.value_history && a.value_history.length > 0 && visibleAgents.has(a.name)
    )

    if (agentsWithHistory.length === 0) return []

    // Collect all timestamps
    const allTimestamps = new Set<string>()
    agentsWithHistory.forEach(agent => {
      agent.value_history.forEach(point => {
        allTimestamps.add(point.timestamp)
      })
    })

    const sortedTimestamps = Array.from(allTimestamps).sort()

    // Build lookup maps
    const lookupMaps: Record<string, Map<string, number>> = {}
    agentsWithHistory.forEach(agent => {
      lookupMaps[agent.name] = new Map(
        agent.value_history.map(p => [p.timestamp, p.value])
      )
    })

    // Downsample if too many points
    const maxPoints = 200
    const step = sortedTimestamps.length > maxPoints
      ? Math.floor(sortedTimestamps.length / maxPoints)
      : 1

    const result: Record<string, number | string>[] = []
    let lastKnown: Record<string, number> = {}

    sortedTimestamps.forEach((ts, idx) => {
      if (idx % step !== 0 && idx !== sortedTimestamps.length - 1) return

      const row: Record<string, number | string> = {
        timestamp: formatTime(ts),
      }

      agentsWithHistory.forEach(agent => {
        const val = lookupMaps[agent.name].get(ts)
        if (val !== undefined) {
          lastKnown[agent.name] = val
        }
        row[agent.name] = lastKnown[agent.name] ?? STARTING_CAPITAL
      })

      result.push(row)
    })

    return result
  }, [agents, visibleAgents])

  const filteredAgents = agents.filter(a => visibleAgents.has(a.name))

  // Y-axis domain
  const allValues = chartData.flatMap(row =>
    agents.map(a => row[a.name] as number).filter(Boolean)
  )
  const minVal = allValues.length > 0 ? Math.min(...allValues) * 0.995 : STARTING_CAPITAL * 0.95
  const maxVal = allValues.length > 0 ? Math.max(...allValues) * 1.005 : STARTING_CAPITAL * 1.05

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div className="card-header mb-0">📈 Portfolio Performance</div>
        <div className="text-xs text-gray-500">
          {chartData.length} data points
        </div>
      </div>

      {/* Agent toggles */}
      <div className="flex flex-wrap gap-2 mb-4">
        {agents.map(agent => {
          const isVisible = visibleAgents.has(agent.name)
          const color = AGENT_COLORS[agent.name] || '#94a3b8'
          const returnPct = agent.total_return_pct
          const isSelected = agent.name === selectedAgentName

          return (
            <button
              key={agent.name}
              onClick={() => toggleAgent(agent.name)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border transition-all ${
                isSelected ? 'ring-1 ring-white' : ''
              } ${
                isVisible
                  ? 'border-opacity-70 bg-opacity-20'
                  : 'border-gray-700 bg-gray-800 opacity-40'
              }`}
              style={isVisible ? {
                borderColor: color,
                backgroundColor: `${color}20`,
                color: color,
              } : {}}
            >
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: isVisible ? color : '#6b7280' }}
              />
              <span className={isVisible ? '' : 'text-gray-500'}>{agent.name}</span>
              <span className={returnPct >= 0 ? 'text-green-400' : 'text-red-400'}>
                {returnPct >= 0 ? '+' : ''}{returnPct.toFixed(1)}%
              </span>
            </button>
          )
        })}
      </div>

      {/* Chart */}
      {chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.5} />
            <XAxis
              dataKey="timestamp"
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[minVal, maxVal]}
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={formatValue}
              width={75}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine
              y={STARTING_CAPITAL}
              stroke="#6b7280"
              strokeDasharray="4 4"
              strokeOpacity={0.6}
            />
            {filteredAgents.map(agent => (
              <Line
                key={agent.name}
                type="monotone"
                dataKey={agent.name}
                stroke={AGENT_COLORS[agent.name] || '#94a3b8'}
                strokeWidth={agent.name === selectedAgentName ? 2.5 : 1.5}
                dot={false}
                activeDot={{ r: 4 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="h-64 flex flex-col items-center justify-center text-gray-500">
          <div className="text-4xl mb-3">📈</div>
          <p className="text-sm">Portfolio history will appear here once trading starts</p>
          <p className="text-xs text-gray-600 mt-1">Click Start to begin the competition</p>
        </div>
      )}

      {/* Starting capital reference note */}
      {chartData.length > 0 && (
        <div className="mt-3 text-xs text-gray-500 flex items-center gap-2">
          <div className="w-6 border-t-2 border-gray-600 border-dashed" />
          Starting capital: $100,000
        </div>
      )}
    </div>
  )
}
