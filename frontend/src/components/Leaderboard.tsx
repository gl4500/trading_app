import React from 'react'
import { Agent } from '../App'

interface LeaderboardProps {
  leaderboard: Agent[]
  selectedAgent: string | null
  onSelectAgent: (name: string) => void
}

const STRATEGY_COLORS: Record<string, string> = {
  TechAgent: 'badge-blue',
  MomentumAgent: 'badge-purple',
  MeanReversionAgent: 'badge-yellow',
  SentimentAgent: 'badge-green',
  ClaudeAgent: 'badge-red',
  EnsembleAgent: 'badge-gray',
  ScannerAgent: 'badge-purple',
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

function formatCurrency(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`
  if (Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return `$${value.toFixed(2)}`
}

function formatPct(value: number): string {
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

export default function Leaderboard({ leaderboard, selectedAgent, onSelectAgent }: LeaderboardProps) {
  const maxValue = Math.max(...leaderboard.map(a => a.total_value), 100000)

  return (
    <div className="card">
      <div className="card-header flex items-center justify-between">
        <span>🏆 Leaderboard</span>
        <span className="text-gray-500 text-xs font-normal">{leaderboard.length} agents</span>
      </div>

      <div className="space-y-2">
        {leaderboard.length === 0 ? (
          <div className="text-center py-8 text-gray-500 text-sm">
            No agents available. Start the competition!
          </div>
        ) : (
          leaderboard.map((agent, idx) => {
            const isSelected = agent.name === selectedAgent
            const isPositive = agent.total_return_pct >= 0
            const barWidth = Math.max(5, (agent.total_value / maxValue) * 100)

            return (
              <div
                key={agent.name}
                onClick={() => onSelectAgent(agent.name)}
                className={`relative p-3 rounded-lg border cursor-pointer transition-all duration-150 ${
                  isSelected
                    ? 'border-blue-500 bg-blue-900/20'
                    : 'border-gray-700/50 bg-gray-800/30 hover:border-gray-600 hover:bg-gray-700/30'
                }`}
              >
                {/* Progress bar background */}
                <div
                  className={`absolute inset-y-0 left-0 rounded-lg opacity-10 transition-all ${
                    isPositive ? 'bg-green-400' : 'bg-red-400'
                  }`}
                  style={{ width: `${barWidth}%` }}
                />

                <div className="relative">
                  {/* Row 1: Rank + Name + Return */}
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      {/* Rank badge */}
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                        idx === 0 ? 'bg-yellow-500 text-yellow-900' :
                        idx === 1 ? 'bg-gray-400 text-gray-900' :
                        idx === 2 ? 'bg-amber-700 text-amber-100' :
                        'bg-gray-700 text-gray-300'
                      }`}>
                        {idx + 1}
                      </div>

                      {/* Agent icon + name */}
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm">{AGENT_ICONS[agent.name] || '🤖'}</span>
                          <span className="font-medium text-sm text-white">{agent.name}</span>
                          {!agent.is_active && (
                            <span className="text-xs text-red-400">(halted)</span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Return percentage */}
                    <div className={`text-sm font-bold ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
                      {formatPct(agent.total_return_pct)}
                    </div>
                  </div>

                  {/* Row 2: Stats */}
                  <div className="flex items-center justify-between text-xs text-gray-400">
                    <span className="font-medium text-gray-200">{formatCurrency(agent.total_value)}</span>
                    <div className="flex gap-3">
                      <span>WR: <span className="text-gray-300">{agent.win_rate.toFixed(0)}%</span></span>
                      <span>Trades: <span className="text-gray-300">{agent.total_trades}</span></span>
                    </div>
                  </div>

                  {/* Strategy badge */}
                  <div className="mt-1.5">
                    <span className={`${STRATEGY_COLORS[agent.name] || 'badge-gray'} text-xs`}>
                      {agent.strategy.split(':')[0].substring(0, 40)}
                    </span>
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Summary stats */}
      {leaderboard.length > 0 && (
        <div className="mt-4 pt-3 border-t border-gray-700/50 grid grid-cols-2 gap-2 text-xs text-gray-400">
          <div>
            Best: <span className="text-green-400 font-medium">
              {formatPct(Math.max(...leaderboard.map(a => a.total_return_pct)))}
            </span>
          </div>
          <div>
            Worst: <span className="text-red-400 font-medium">
              {formatPct(Math.min(...leaderboard.map(a => a.total_return_pct)))}
            </span>
          </div>
          <div>
            Avg Return: <span className="text-gray-200 font-medium">
              {formatPct(leaderboard.reduce((s, a) => s + a.total_return_pct, 0) / leaderboard.length)}
            </span>
          </div>
          <div>
            Total Trades: <span className="text-gray-200 font-medium">
              {leaderboard.reduce((s, a) => s + a.total_trades, 0)}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
