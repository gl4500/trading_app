import React, { useState } from 'react'
import { Agent } from '../App'

interface AgentCardProps {
  agent: Agent
  prices: Record<string, number>
}

const AGENT_ICONS: Record<string, string> = {
  TechAgent: '📊',
  MomentumAgent: '🚀',
  MeanReversionAgent: '🔄',
  SentimentAgent: '💭',
  ClaudeAgent: '🧠',
  EnsembleAgent: '🎯',
  ScannerAgent: '⟁',
}

const AGENT_COLORS: Record<string, string> = {
  TechAgent: 'blue',
  MomentumAgent: 'purple',
  MeanReversionAgent: 'yellow',
  SentimentAgent: 'green',
  ClaudeAgent: 'red',
  EnsembleAgent: 'gray',
  ScannerAgent: 'purple',
}

function MetricTile({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-gray-900/50 rounded-lg p-3 border border-gray-700/30">
      <div className={`text-lg font-bold ${color || 'text-white'}`}>{value}</div>
      <div className="text-xs text-gray-400">{label}</div>
      {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
    </div>
  )
}

export default function AgentCard({ agent, prices }: AgentCardProps) {
  const [showAllSignals, setShowAllSignals] = useState(false)
  const color = AGENT_COLORS[agent.name] || 'gray'
  const isPositive = agent.total_return_pct >= 0

  const returnColor = isPositive ? 'text-green-400' : 'text-red-400'
  const cashPct = agent.total_value > 0 ? (agent.cash / agent.total_value) * 100 : 100

  const unrealizedGain = (agent.positions || []).reduce((sum, pos) => sum + pos.unrealized_pnl, 0)
  const unrealizedPct = agent.total_value > 0 ? (unrealizedGain / (agent.total_value - unrealizedGain)) * 100 : 0
  const realizedProfit = agent.total_return - unrealizedGain
  const realizedPct = agent.total_value > 0 ? (realizedProfit / (agent.total_value - unrealizedGain)) * 100 : 0

  const signals = Object.entries(agent.last_signals || {})
  const displaySignals = showAllSignals ? signals : signals.slice(0, 3)

  function formatCurrency(v: number) {
    return `$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }

  function formatPct(v: number) {
    return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
  }

  return (
    <div className="space-y-4">
      {/* Header card */}
      <div className="card">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className={`text-3xl`}>{AGENT_ICONS[agent.name] || '🤖'}</div>
            <div>
              <h2 className="text-xl font-bold text-white">{agent.name}</h2>
              <p className="text-sm text-gray-400">{agent.strategy}</p>
            </div>
          </div>
          <div className="text-right">
            {agent.is_active ? (
              <span className="badge-green text-xs">Active</span>
            ) : (
              <span className="badge-red text-xs">Halted</span>
            )}
          </div>
        </div>

        {/* Key metrics grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-4">
          <MetricTile
            label="Total Return"
            value={formatPct(agent.total_return_pct)}
            sub={`${agent.total_return >= 0 ? '+' : ''}${formatCurrency(agent.total_return)}`}
            color={returnColor}
          />
          <MetricTile
            label="Unrealized Gain"
            value={`${unrealizedGain >= 0 ? '+' : '-'}${formatCurrency(unrealizedGain)}`}
            sub={formatPct(unrealizedPct)}
            color={unrealizedGain >= 0 ? 'text-green-400' : 'text-red-400'}
          />
          <MetricTile
            label="Realized Profit"
            value={`${realizedProfit >= 0 ? '+' : '-'}${formatCurrency(realizedProfit)}`}
            sub={formatPct(realizedPct)}
            color={realizedProfit >= 0 ? 'text-green-400' : 'text-red-400'}
          />
          <MetricTile
            label="Win Rate"
            value={`${agent.win_rate < 50 ? '-' : ''}${agent.win_rate.toFixed(1)}%`}
            sub={`${agent.total_trades} trades`}
            color={agent.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}
          />
          <MetricTile
            label="Sharpe Ratio"
            value={agent.sharpe_ratio.toFixed(3)}
            sub={`MaxDD: ${agent.max_drawdown.toFixed(1)}%`}
            color={agent.sharpe_ratio > 0 ? 'text-blue-400' : 'text-yellow-400'}
          />
        </div>

        {/* Exit Quality — MAE/MFE (only shown once there's excursion data) */}
        {(agent.avg_mfe ?? 0) > 0 && (
          <div className="bg-gray-900/40 rounded-lg p-3 border border-gray-700/30 mb-4">
            <div className="text-xs text-gray-400 font-semibold mb-2 uppercase tracking-wide">Exit Quality</div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <div className="text-sm font-bold text-red-400">
                  {(agent.avg_mae ?? 0).toFixed(1)}%
                </div>
                <div className="text-xs text-gray-500">Avg MAE</div>
                <div className="text-xs text-gray-600">deepest dip</div>
              </div>
              <div>
                <div className="text-sm font-bold text-green-400">
                  {(agent.avg_mfe ?? 0).toFixed(1)}%
                </div>
                <div className="text-xs text-gray-500">Avg MFE</div>
                <div className="text-xs text-gray-600">highest peak</div>
              </div>
              <div>
                <div className={`text-sm font-bold ${(agent.avg_captured_pct ?? 0) >= 50 ? 'text-blue-400' : 'text-yellow-400'}`}>
                  {(agent.avg_captured_pct ?? 0).toFixed(0)}%
                </div>
                <div className="text-xs text-gray-500">Captured</div>
                <div className="text-xs text-gray-600">of peak kept</div>
              </div>
            </div>
            {/* Visual bar: captured vs left on table */}
            <div className="mt-2">
              <div className="flex justify-between text-xs text-gray-600 mb-1">
                <span>captured</span>
                <span>left on table</span>
              </div>
              <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full transition-all"
                  style={{ width: `${Math.min(100, Math.max(0, agent.avg_captured_pct ?? 0))}%` }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Cash vs Position bar */}
        <div>
          <div className="flex justify-between text-xs text-gray-400 mb-1.5">
            <span>Cash: {formatCurrency(agent.cash)} ({cashPct.toFixed(1)}%)</span>
            <span>Invested: {formatCurrency(agent.position_value)} ({(100 - cashPct).toFixed(1)}%)</span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-green-500 to-blue-500 rounded-full transition-all"
              style={{ width: `${100 - cashPct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Positions table */}
      {agent.positions && agent.positions.length > 0 && (
        <div className="card">
          <div className="card-header">Current Positions ({agent.positions.length})</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="table-header text-left">Symbol</th>
                  <th className="table-header text-right">Shares</th>
                  <th className="table-header text-right">Avg Cost</th>
                  <th className="table-header text-right">Current</th>
                  <th className="table-header text-right">Value</th>
                  <th className="table-header text-right">P&L ($)</th>
                  <th className="table-header text-right">P&L (%)</th>
                  <th className="table-header text-right">Entry Conf</th>
                  <th className="table-header text-right">Bayes</th>
                </tr>
              </thead>
              <tbody>
                {agent.positions.map(pos => {
                  const pnlColor = pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  const pnlSign = pos.unrealized_pnl >= 0 ? '+' : '-'
                  const pnlAbs = Math.abs(pos.unrealized_pnl)
                  const pctSign = pos.unrealized_pnl_pct >= 0 ? '+' : '-'
                  const pctAbs = Math.abs(pos.unrealized_pnl_pct)
                  const entryConf = pos.entry_confidence ?? 0.5
                  const bayesConf = pos.bayes_confidence ?? entryConf
                  const confDrop = entryConf - bayesConf
                  // Color: green = stable, yellow = 10-20pp drop, red = 20pp+ drop (exit threshold is 30pp)
                  const bayesColor = confDrop >= 0.20 ? 'text-red-400' : confDrop >= 0.10 ? 'text-yellow-400' : 'text-green-400'
                  return (
                    <tr key={pos.symbol} className="table-row">
                      <td className="table-cell font-bold text-blue-400">{pos.symbol}</td>
                      <td className="table-cell text-right text-gray-300">{pos.shares.toFixed(2)}</td>
                      <td className="table-cell text-right text-gray-400">${pos.avg_cost.toFixed(2)}</td>
                      <td className="table-cell text-right text-gray-300">${pos.current_price.toFixed(2)}</td>
                      <td className="table-cell text-right font-medium">{formatCurrency(pos.current_value)}</td>
                      <td className={`table-cell text-right font-bold ${pnlColor}`}>
                        {pnlSign}${pnlAbs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td className={`table-cell text-right font-bold ${pnlColor}`}>
                        {pctSign}{pctAbs.toFixed(2)}%
                      </td>
                      <td className="table-cell text-right text-gray-400">{(entryConf * 100).toFixed(0)}%</td>
                      <td className={`table-cell text-right font-medium ${bayesColor}`}>{(bayesConf * 100).toFixed(0)}%</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Scanner-specific hint when no signals yet */}
      {signals.length === 0 && agent.name === 'ScannerAgent' && (
        <div className="card border-dashed border-gray-700 text-center py-6 space-y-1">
          <div className="text-2xl text-gray-600">⟁</div>
          <p className="text-sm text-gray-400 font-medium">No signals yet</p>
          <p className="text-xs text-gray-600">
            Run a scan first — ScannerAgent will trade on the next cycle after results are cached.
          </p>
        </div>
      )}

      {/* Last signals */}
      {signals.length > 0 && (
        <div className="card">
          <div className="card-header flex justify-between items-center">
            <span>Last AI Decisions</span>
            {signals.length > 3 && (
              <button
                onClick={() => setShowAllSignals(!showAllSignals)}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                {showAllSignals ? 'Show less' : `Show all (${signals.length})`}
              </button>
            )}
          </div>
          <div className="space-y-2">
            {displaySignals.map(([symbol, signal]) => (
              <div key={symbol} className="bg-gray-900/50 rounded-lg p-2.5 border border-gray-700/30">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-blue-400">{symbol}</span>
                    <span className={`badge text-xs ${
                      signal.action === 'BUY' ? 'badge-green' :
                      signal.action === 'SELL' ? 'badge-red' : 'badge-gray'
                    }`}>
                      {signal.action}
                    </span>
                  </div>
                  <span className="text-xs text-gray-500">
                    conf: {(signal.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-xs text-gray-400 leading-relaxed line-clamp-2">
                  {signal.reasoning}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
