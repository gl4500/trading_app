import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LeaderboardV2 from '../LeaderboardV2'
import type { Agent } from '../../App'

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 1,
    name: 'TechAgent',
    strategy: 'RSI/MACD/Bollinger',
    is_active: true,
    cash: 95000, total_value: 105000, position_value: 10000,
    total_return_pct: 5.0, total_return: 5000,
    win_rate: 60, sharpe_ratio: 1.2, max_drawdown: 3.5,
    total_trades: 12,
    positions: [], recent_trades: [], last_signals: {},
    value_history: [
      { timestamp: '2026-04-21T10:00:00Z', value: 100000 },
      { timestamp: '2026-04-21T11:00:00Z', value: 102000 },
      { timestamp: '2026-04-21T12:00:00Z', value: 105000 },
    ],
    ...overrides,
  }
}

describe('LeaderboardV2', () => {
  it('renders all agents with rank, name, and return', () => {
    const agents = [makeAgent({ name: 'TechAgent', total_return_pct: 5 }),
                    makeAgent({ name: 'ClaudeAgent', total_return_pct: -2 })]
    render(<LeaderboardV2 leaderboard={agents} selected={null} onSelect={() => {}} />)
    expect(screen.getByText('TechAgent')).toBeInTheDocument()
    expect(screen.getByText('ClaudeAgent')).toBeInTheDocument()
    expect(screen.getByText('+5.00%')).toBeInTheDocument()
    expect(screen.getByText('-2.00%')).toBeInTheDocument()
  })

  it('shows HALTED badge for inactive agents', () => {
    const agents = [makeAgent({ is_active: false })]
    render(<LeaderboardV2 leaderboard={agents} selected={null} onSelect={() => {}} />)
    expect(screen.getByText('HALTED')).toBeInTheDocument()
  })

  it('renders a sparkline svg per agent with value history', () => {
    const agents = [makeAgent({ name: 'A1' })]
    const { container } = render(<LeaderboardV2 leaderboard={agents} selected={null} onSelect={() => {}} />)
    const sparks = container.querySelectorAll('[data-testid="sparkline"]')
    expect(sparks).toHaveLength(1)
  })

  it('calls onSelect with agent name on click', async () => {
    const onSelect = vi.fn()
    const agents = [makeAgent({ name: 'TechAgent' })]
    render(<LeaderboardV2 leaderboard={agents} selected={null} onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('button', { name: /TechAgent/ }))
    expect(onSelect).toHaveBeenCalledWith('TechAgent')
  })

  it('renders empty state when no agents', () => {
    render(<LeaderboardV2 leaderboard={[]} selected={null} onSelect={() => {}} />)
    expect(screen.getByText(/no agents/i)).toBeInTheDocument()
  })
})
