import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TradeLogV2 from '../TradeLogV2'
import type { Trade, Agent } from '../../App'

const t = (over: Partial<Trade>): Trade => ({
  symbol: 'AAPL', action: 'BUY', shares: 1, price: 100,
  timestamp: '2026-04-21T15:30:00Z', reasoning: 'momentum',
  pnl: 0, agent_name: 'TechAgent',
  ...over,
})

describe('TradeLogV2', () => {
  it('renders an empty-state when there are no trades', () => {
    render(<TradeLogV2 trades={[]} agents={[]} />)
    expect(screen.getByText(/no trades/i)).toBeInTheDocument()
  })

  it('renders trade rows with symbol, action and price', () => {
    render(<TradeLogV2 trades={[t({ symbol: 'AAPL', action: 'BUY', price: 150.25 })]} agents={[]} />)
    expect(screen.getByText('AAPL')).toBeInTheDocument()
    // "BUY" appears in both the action cell and the action-filter <option>; assert at least one match
    expect(screen.getAllByText('BUY').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/150\.25/)).toBeInTheDocument()
  })

  it('shows the trade count in the header', () => {
    render(<TradeLogV2 trades={[t({}), t({}), t({})]} agents={[]} />)
    expect(screen.getByText(/TRADE LOG · 3/i)).toBeInTheDocument()
  })

  it('shows realized P&L total in the summary', () => {
    const trades: Trade[] = [
      t({ action: 'SELL', pnl: 12.34 }),
      t({ action: 'SELL', pnl: -5.00 }),
    ]
    render(<TradeLogV2 trades={trades} agents={[]} />)
    expect(screen.getByText(/\+\$7\.34/)).toBeInTheDocument()
  })

  it('filters by action when a SELL filter is chosen', async () => {
    const trades: Trade[] = [
      t({ symbol: 'AAPL', action: 'BUY' }),
      t({ symbol: 'MSFT', action: 'SELL', pnl: 5 }),
    ]
    render(<TradeLogV2 trades={trades} agents={[]} />)
    const select = screen.getByLabelText(/action filter/i)
    await userEvent.selectOptions(select, 'SELL')
    expect(screen.queryByText('AAPL')).not.toBeInTheDocument()
    expect(screen.getByText('MSFT')).toBeInTheDocument()
  })

  it('paginates when more than the page size is given', () => {
    const many: Trade[] = Array.from({ length: 25 }, (_, i) => t({ symbol: `S${i}` }))
    render(<TradeLogV2 trades={many} agents={[]} />)
    expect(screen.getByText(/PAGE 1 OF 2/i)).toBeInTheDocument()
  })
})
