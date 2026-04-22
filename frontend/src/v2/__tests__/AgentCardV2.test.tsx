import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import AgentCardV2 from '../AgentCardV2'
import type { Agent } from '../../App'

const baseAgent: Agent = {
  id: 1,
  name: 'TechAgent',
  strategy: 'Technical analysis',
  is_active: true,
  cash: 5000,
  total_value: 11234.50,
  position_value: 6234.50,
  total_return_pct: 12.34,
  total_return: 1234.50,
  win_rate: 62.5,
  sharpe_ratio: 1.234,
  max_drawdown: 4.2,
  total_trades: 8,
  positions: [],
  recent_trades: [],
  last_signals: {},
  value_history: [],
}

describe('AgentCardV2', () => {
  it('renders the agent name as a header', () => {
    render(<AgentCardV2 agent={baseAgent} prices={{}} />)
    expect(screen.getByText(/TECHAGENT/i)).toBeInTheDocument()
  })

  it('renders total return with a sign', () => {
    render(<AgentCardV2 agent={baseAgent} prices={{}} />)
    expect(screen.getByText(/\+12\.34%/)).toBeInTheDocument()
  })

  it('shows ACTIVE status when agent.is_active is true', () => {
    render(<AgentCardV2 agent={baseAgent} prices={{}} />)
    expect(screen.getByText(/ACTIVE/)).toBeInTheDocument()
  })

  it('shows HALTED status when agent.is_active is false', () => {
    render(<AgentCardV2 agent={{ ...baseAgent, is_active: false }} prices={{}} />)
    expect(screen.getByText(/HALTED/)).toBeInTheDocument()
  })

  it('renders position rows when positions are present', () => {
    const agent: Agent = {
      ...baseAgent,
      positions: [{
        symbol: 'AAPL', shares: 10.5, avg_cost: 150.23, current_price: 165.40,
        current_value: 1736.70, unrealized_pnl: 159.29, unrealized_pnl_pct: 10.05,
      }],
    }
    render(<AgentCardV2 agent={agent} prices={{}} />)
    expect(screen.getByText('AAPL')).toBeInTheDocument()
    expect(screen.getByText(/\+10\.05%/)).toBeInTheDocument()
  })

  it('renders signal entries with action labels when signals are present', () => {
    const agent: Agent = {
      ...baseAgent,
      last_signals: {
        AAPL: { action: 'BUY', confidence: 0.78, reasoning: 'Momentum confirmed.', timestamp: '' },
      },
    }
    render(<AgentCardV2 agent={agent} prices={{}} />)
    expect(screen.getByText(/BUY/)).toBeInTheDocument()
    expect(screen.getByText(/Momentum confirmed/)).toBeInTheDocument()
  })
})
