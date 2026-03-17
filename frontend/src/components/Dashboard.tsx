import React, { useState } from 'react'
import { Agent, Trade } from '../App'
import Leaderboard from './Leaderboard'
import AgentCard from './AgentCard'
import PortfolioChart from './PortfolioChart'
import TradeLog from './TradeLog'
import MarketOverview from './MarketOverview'
import SignalsPanel from './SignalsPanel'
import ScannerPanel from './ScannerPanel'
import SummaryPanel from './SummaryPanel'
import SentinelPanel from './SentinelPanel'

interface DashboardProps {
  agents: Agent[]
  prices: Record<string, number>
  leaderboard: Agent[]
  trades: Trade[]
  watchlist: string[]
  isRunning: boolean
}

export default function Dashboard({
  agents,
  prices,
  leaderboard,
  trades,
  watchlist,
  isRunning,
}: DashboardProps) {
  const [selectedAgentName, setSelectedAgentName] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'chart' | 'detail' | 'signals' | 'scanner' | 'summary' | 'sentinel' | 'trades'>('chart')

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
      <MarketOverview prices={prices} watchlist={watchlist} />

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left: Leaderboard */}
        <div className="lg:col-span-1">
          <Leaderboard
            leaderboard={leaderboard}
            selectedAgent={selectedAgentName}
            onSelectAgent={handleSelectAgent}
          />
        </div>

        {/* Right: Charts & Detail */}
        <div className="lg:col-span-2 space-y-4">
          {/* Tab Controls */}
          <div className="flex gap-2">
            <button
              onClick={() => setActiveTab('chart')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'chart'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              Portfolio Chart
            </button>
            <button
              onClick={() => setActiveTab('detail')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'detail'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              Agent Detail
            </button>
            <button
              onClick={() => setActiveTab('signals')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'signals'
                  ? 'bg-purple-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              Signals ✦
            </button>
            <button
              onClick={() => setActiveTab('scanner')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'scanner'
                  ? 'bg-violet-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              ⟁ Scanner
            </button>
            <button
              onClick={() => setActiveTab('summary')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'summary'
                  ? 'bg-amber-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              ◈ Daily Roll-Up
            </button>
            <button
              onClick={() => setActiveTab('sentinel')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'sentinel'
                  ? 'bg-orange-700 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              ⚡ Sentinel
            </button>
            <button
              onClick={() => setActiveTab('trades')}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeTab === 'trades'
                  ? 'bg-gray-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              }`}
            >
              📋 Trades
            </button>
            {displayAgent && activeTab !== 'signals' && activeTab !== 'scanner' && activeTab !== 'summary' && activeTab !== 'sentinel' && activeTab !== 'trades' && (
              <span className="ml-auto text-xs text-gray-400 self-center">
                Viewing: <span className="text-blue-400 font-medium">{displayAgent.name}</span>
              </span>
            )}
          </div>

          {activeTab === 'chart' && (
            <PortfolioChart
              agents={agents}
              selectedAgentName={selectedAgentName}
            />
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
        </div>
      </div>
    </div>
  )
}
