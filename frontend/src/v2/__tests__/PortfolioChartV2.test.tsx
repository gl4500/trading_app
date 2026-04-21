import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import PortfolioChartV2 from '../PortfolioChartV2'
import type { Agent } from '../../App'

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class {
    observe() {} unobserve() {} disconnect() {}
  })
})

function makeAgent(name: string, values: number[]): Agent {
  return {
    id: 1, name, strategy: '', is_active: true,
    cash: 0, total_value: values[values.length - 1] ?? 0, position_value: 0,
    total_return_pct: 0, total_return: 0,
    win_rate: 0, sharpe_ratio: 0, max_drawdown: 0, total_trades: 0,
    positions: [], recent_trades: [], last_signals: {},
    value_history: values.map((v, i) => ({
      timestamp: new Date(2026, 3, 21, 10 + i).toISOString(), value: v,
    })),
  }
}

describe('PortfolioChartV2', () => {
  it('renders a header with PORTFOLIO label', () => {
    render(<PortfolioChartV2 agents={[]} selectedName={null} />)
    expect(screen.getByText(/PORTFOLIO/)).toBeInTheDocument()
  })

  it('shows an empty-state message when no agents have history', () => {
    render(<PortfolioChartV2 agents={[]} selectedName={null} />)
    expect(screen.getByText(/no data/i)).toBeInTheDocument()
  })

  it('renders agent toggle pills when agents have history', () => {
    const agents = [makeAgent('TechAgent', [100000, 102000])]
    render(<PortfolioChartV2 agents={agents} selectedName={null} />)
    expect(screen.getByRole('button', { name: /TechAgent/ })).toBeInTheDocument()
  })
})
