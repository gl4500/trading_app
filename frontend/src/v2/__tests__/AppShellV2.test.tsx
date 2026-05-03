import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AppShellV2 from '../AppShellV2'
import type { AppData, Trade } from '../../App'

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class {
    observe() {} unobserve() {} disconnect() {}
  })
})

const baseData: AppData = {
  agents: [], prices: {}, price_changes: {}, leaderboard: [],
  is_running: false, cycle_count: 0,
  timestamp: new Date().toISOString(), watchlist: [],
}

const noopTrades: Trade[] = []

describe('AppShellV2', () => {
  it('renders sidebar, command strip, and content area', () => {
    render(<AppShellV2 data={baseData} trades={noopTrades} wsConnected={true} ollamaOnly={true} />)
    expect(screen.getByRole('navigation', { name: /primary/i })).toBeInTheDocument()
    expect(screen.getByText('LIVE')).toBeInTheDocument()
    expect(screen.getByText('PERFORMANCE')).toBeInTheDocument()
  })

  it('switches content when a sidebar item is clicked', async () => {
    render(<AppShellV2 data={baseData} trades={noopTrades} wsConnected={true} ollamaOnly={true} />)
    expect(screen.getByText(/PORTFOLIO/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /scanner/i }))
    expect(screen.queryByText(/PORTFOLIO/)).not.toBeInTheDocument()
  })

  it('counts halted agents into the command strip', () => {
    const data: AppData = {
      ...baseData,
      agents: [
        { id: 1, name: 'A', strategy: '', is_active: false,
          cash: 0, total_value: 0, position_value: 0,
          total_return_pct: 0, total_return: 0,
          win_rate: 0, sharpe_ratio: 0, max_drawdown: 0, total_trades: 0,
          positions: [], recent_trades: [], last_signals: {}, value_history: [] },
      ],
    }
    render(<AppShellV2 data={data} trades={noopTrades} wsConnected={true} ollamaOnly={true} />)
    expect(screen.getByText(/1 HALTED/)).toBeInTheDocument()
  })
})
