import React, { useState } from 'react'
import { Agent, Trade } from '../App'
import Leaderboard from './Leaderboard'
import AgentCard from './AgentCard'
import PortfolioChart from './PortfolioChart'
import TradeLog from './TradeLog'
import MarketOverview from './MarketOverview'
import BenchmarkPanel from './BenchmarkPanel'
import SignalsPanel from './SignalsPanel'
import ScannerPanel from './ScannerPanel'
import SummaryPanel from './SummaryPanel'
import SentinelPanel from './SentinelPanel'
import TokensPanel from './TokensPanel'
import ErrorLogPanel from './ErrorLogPanel'
import TelemetryPanel from './TelemetryPanel'

interface DashboardProps {
  agents: Agent[]
  prices: Record<string, number>
  priceChanges: Record<string, number>
  leaderboard: Agent[]
  trades: Trade[]
  watchlist: string[]
  isRunning: boolean
}

export default function Dashboard({
  agents,
  prices,
  priceChanges,
  leaderboard,
  trades,
  watchlist,
  isRunning,
}: DashboardProps) {
  const [selectedAgentName, setSelectedAgentName] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'chart' | 'detail' | 'signals' | 'scanner' | 'summary' | 'sentinel' | 'trades' | 'tokens' | 'errors' | 'telemetry'>('chart')

  function handleSelectAgent(name: string) {
    setSelectedAgentName(name)
    setActiveTab('detail')
  }

  const selectedAgent = agents.find(a => a.name === selectedAgentName) || null

  // Default to top performer
  const displayAgent = selectedAgent || (leaderboard.length > 0 ? leaderboard[0] : null)

  return (
    <div className="space-y-4">
      {/* Market Overview Ticker */}
      <MarketOverview prices={prices} priceChanges={priceChanges} watchlist={watchlist} />

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left: Benchmarks (Portfolio vs SPY vs DJIA) + Leaderboard */}
        <div className="lg:col-span-1 space-y-3">
          <BenchmarkPanel />
          <Leaderboard
            leaderboard={leaderboard}
            selectedAgent={selectedAgentName}
            onSelectAgent={handleSelectAgent}
          />
        </div>

        {/* Right: Charts & Detail */}
        <div className="lg:col-span-2 space-y-4">
          {/* Tab Controls */}
          <div className="flex gap-2 overflow-x-auto pb-1">
            <button
              onClick={() => setActiveTab('chart')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'chart'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              Portfolio Chart
            </button>
            <button
              onClick={() => setActiveTab('detail')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'detail'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              Agent Detail
            </button>
            <button
              onClick={() => setActiveTab('signals')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'signals'
                  ? 'bg-purple-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              Signals ✦
            </button>
            <button
              onClick={() => setActiveTab('scanner')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'scanner'
                  ? 'bg-violet-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              ⟁ Scanner
            </button>
            <button
              onClick={() => setActiveTab('summary')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'summary'
                  ? 'bg-amber-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              ◈ Daily Roll-Up
            </button>
            <button
              onClick={() => setActiveTab('sentinel')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'sentinel'
                  ? 'bg-orange-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              ⚡ Sentinel
            </button>
            <button
              onClick={() => setActiveTab('trades')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'trades'
                  ? 'bg-gray-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              📋 Trades
            </button>
            <button
              onClick={() => setActiveTab('tokens')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'tokens'
                  ? 'bg-teal-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              🔢 Tokens
            </button>
            <button
              onClick={() => setActiveTab('errors')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'errors'
                  ? 'bg-red-800 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              ⚠ Errors
            </button>
            <button
              onClick={() => setActiveTab('telemetry')}
              className={`shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'telemetry'
                  ? 'bg-purple-800 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              📊 Telemetry
            </button>
            {displayAgent && activeTab !== 'signals' && activeTab !== 'scanner' && activeTab !== 'summary' && activeTab !== 'sentinel' && activeTab !== 'trades' && activeTab !== 'tokens' && activeTab !== 'errors' && activeTab !== 'telemetry' && (
              <span className="ml-auto text-xs text-gray-400 self-center">
                Viewing: <span className="text-blue-400 font-medium">{displayAgent.name}</span>
              </span>
            )}
          </div>

          {activeTab === 'chart' && (
            <div className="space-y-4">
              <PortfolioChart
                agents={agents}
                selectedAgentName={selectedAgentName}
              />

              {/* Per-agent trade summary */}
              {displayAgent && (() => {
                const sells = displayAgent.recent_trades.filter(t => t.action === 'SELL')
                const buys  = displayAgent.recent_trades.filter(t => t.action === 'BUY')
                const realizedPnl = sells.reduce((s, t) => s + (t.pnl ?? 0), 0)
                const pnlColor = realizedPnl >= 0 ? 'text-green-400' : 'text-red-400'
                const pnlSign  = realizedPnl >= 0 ? '+$' : '-$'

                return (
                  <div className="card">
                    <div className="flex items-center justify-between mb-3">
                      <span className="card-header">Recent Trades — {displayAgent.name}</span>
                      <div className="flex items-center gap-4 text-xs text-gray-400">
                        <span><span className="text-green-400 font-medium">{buys.length}</span> buys</span>
                        <span><span className="text-red-400 font-medium">{sells.length}</span> sells</span>
                        <span>Realized P&L: <span className={`font-bold ${pnlColor}`}>{pnlSign}{Math.abs(realizedPnl).toFixed(2)}</span></span>
                        <span>Win rate: <span className={`font-bold ${displayAgent.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}`}>{displayAgent.win_rate < 50 ? '-' : ''}{displayAgent.win_rate.toFixed(1)}%</span></span>
                      </div>
                    </div>

                    {displayAgent.recent_trades.length === 0 ? (
                      <p className="text-center text-gray-500 text-sm py-4">No trades recorded yet.</p>
                    ) : (
                      <div className="divide-y divide-gray-800/60">
                        {displayAgent.recent_trades.map((t, i) => {
                          const isSell = t.action === 'SELL'
                          const pnl = t.pnl ?? 0
                          return (
                            <div key={i} className="flex items-center gap-3 px-1 py-1.5 text-xs">
                              <span className="text-gray-500 w-20 shrink-0 font-mono leading-tight">
                                <span className="block">{new Date(t.timestamp).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}</span>
                                <span className="block text-gray-600">{new Date(t.timestamp).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</span>
                              </span>
                              <span className={`font-bold w-8 shrink-0 ${t.action === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>
                                {t.action}
                              </span>
                              <span className="font-bold text-white w-14 shrink-0">{t.symbol}</span>
                              <span className="text-gray-400">{t.shares.toFixed(2)} @ ${t.price.toFixed(2)}</span>
                              {isSell && (
                                <span className={`ml-auto font-bold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                  {pnl >= 0 ? '+$' : '-$'}{Math.abs(pnl).toFixed(2)}
                                </span>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })()}
            </div>
          )}

          {activeTab === 'detail' && displayAgent && (
            <AgentCard agent={displayAgent} prices={prices} />
          )}

          {activeTab === 'detail' && !displayAgent && (
            <div className="card flex items-center justify-center h-48 text-gray-500">
              Select an agent from the leaderboard to view details
            </div>
          )}

          {activeTab === 'signals' && <SignalsPanel />}

          {activeTab === 'scanner' && <ScannerPanel />}

          {activeTab === 'summary' && <SummaryPanel />}

          {activeTab === 'sentinel' && <SentinelPanel />}

          {activeTab === 'trades' && <TradeLog trades={trades} agents={agents} />}

          {activeTab === 'tokens' && <TokensPanel />}

          {activeTab === 'errors' && <ErrorLogPanel />}

          {activeTab === 'telemetry' && <TelemetryPanel />}
        </div>
      </div>
    </div>
  )
}
