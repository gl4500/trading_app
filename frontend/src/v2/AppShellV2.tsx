import React, { useEffect, useMemo, useState } from 'react'
import SidebarV2, { TabId } from './SidebarV2'
import CommandStripV2 from './CommandStripV2'
import LeaderboardV2 from './LeaderboardV2'
import PortfolioChartV2 from './PortfolioChartV2'
import type { AppData, Trade } from '../App'

import AgentCardV2 from './AgentCardV2'
import TradeLogV2 from './TradeLogV2'
import SignalsPanelV2 from './SignalsPanelV2'
import ScannerPanelV2 from './ScannerPanelV2'
import SummaryPanelV2 from './SummaryPanelV2'
import SentinelPanelV2 from './SentinelPanelV2'
import TokensPanelV2 from './TokensPanelV2'
import ErrorLogPanelV2 from './ErrorLogPanelV2'
import TelemetryPanelV2 from './TelemetryPanelV2'
import RegimeV2 from './RegimeV2'
import CNNDiagnosticsV2 from './CNNDiagnosticsV2'
import DriftV2 from './DriftV2'
import TaxV2 from './TaxV2'

interface Props {
  data: AppData
  trades: Trade[]
  wsConnected: boolean
  ollamaOnly: boolean
}

function todayKey() {
  const d = new Date()
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

function realizedPnlToday(trades: Trade[]) {
  const today = todayKey()
  return trades
    .filter(t => {
      const d = new Date(t.timestamp)
      return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}` === today && t.action === 'SELL'
    })
    .reduce((s, t) => s + (t.pnl ?? 0), 0)
}

function Placeholder({ label }: { label: string }) {
  return (
    <div style={{
      padding: 32, textAlign: 'center',
      color: 'var(--text-dim)', fontFamily: 'var(--font-mono)',
      fontSize: 12, letterSpacing: '0.15em',
      border: '1px dashed var(--border-soft)',
      borderRadius: 'var(--radius-md)',
      background: 'var(--bg-panel)',
    }}>
      {label} · NOT YET WIRED
    </div>
  )
}

export default function AppShellV2({ data, trades, wsConnected, ollamaOnly }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>('chart')
  const [selectedName, setSelectedName] = useState<string | null>(null)

  useEffect(() => {
    document.documentElement.setAttribute('data-ui', 'v2')
    return () => { document.documentElement.removeAttribute('data-ui') }
  }, [])

  const haltedCount = useMemo(
    () => data.agents.filter(a => !a.is_active).length,
    [data.agents]
  )

  const pnlToday = useMemo(() => realizedPnlToday(trades), [trades])

  const selectedAgent = data.agents.find(a => a.name === selectedName)
                      ?? (data.leaderboard.length > 0 ? data.leaderboard[0] : null)

  function handleSelect(name: string) {
    setSelectedName(name)
    setActiveTab('detail')
  }

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '200px 1fr',
      minHeight: '100vh',
      background: 'var(--bg-base)',
      color: 'var(--text-primary)',
      fontFamily: 'var(--font-display)',
    }}>
      <SidebarV2 active={activeTab} onSelect={setActiveTab} />

      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <CommandStripV2
          wsConnected={wsConnected}
          isRunning={data.is_running}
          ollamaOnly={ollamaOnly}
          haltedAgentCount={haltedCount}
          driftWarningCount={0}
          realizedPnlToday={pnlToday}
          cycleCount={data.cycle_count}
        />

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(280px, 320px) 1fr',
          gap: 12,
          padding: 12,
          minHeight: 0,
        }}>
          <div style={{ minWidth: 0 }}>
            <LeaderboardV2
              leaderboard={data.leaderboard}
              selected={selectedName}
              onSelect={handleSelect}
            />
          </div>

          <div style={{ minWidth: 0 }}>
            {activeTab === 'chart' && (
              <PortfolioChartV2 agents={data.agents} selectedName={selectedName} />
            )}
            {activeTab === 'detail' && selectedAgent && (
              <AgentCardV2 agent={selectedAgent} prices={data.prices} />
            )}
            {activeTab === 'detail' && !selectedAgent && (
              <Placeholder label="SELECT AN AGENT" />
            )}
            {activeTab === 'trades' && <TradeLogV2 trades={trades} agents={data.agents} />}
            {activeTab === 'rollup' && <SummaryPanelV2 />}
            {activeTab === 'signals' && <SignalsPanelV2 />}
            {activeTab === 'scanner' && <ScannerPanelV2 />}
            {activeTab === 'sentinel' && <SentinelPanelV2 />}
            {activeTab === 'regime' && <RegimeV2 />}
            {activeTab === 'cnn' && <CNNDiagnosticsV2 />}
            {activeTab === 'drift' && <DriftV2 />}
            {activeTab === 'tax' && <TaxV2 />}
            {activeTab === 'tokens' && <TokensPanelV2 />}
            {activeTab === 'errors' && <ErrorLogPanelV2 />}
            {activeTab === 'telemetry' && <TelemetryPanelV2 />}
          </div>
        </div>
      </div>
    </div>
  )
}
