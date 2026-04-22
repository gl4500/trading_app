import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import SummaryPanelV2 from '../SummaryPanelV2'

const sampleSummary = {
  status: 'ok',
  generated_at: '2026-04-21T15:00:00Z',
  date: '2026-04-21',
  market_status: 'open',
  narrative: 'Markets rallied on Fed dovish tone.',
  agent_summaries: {
    TechAgent: {
      buy_count: 3,
      sell_count: 1,
      hold_count: 2,
      total_return_pct: 5.4,
      win_rate: 0.62,
      active_picks: ['AAPL', 'NVDA'],
      top_buys: [{ symbol: 'AAPL', confidence: 0.9, reasoning: 'Strong momentum' }],
      top_sells: [],
      trades_today: [],
    },
  },
  consensus: {
    AAPL: {
      consensus: 'STRONG BUY',
      buy_votes:  [{ agent: 'TechAgent', confidence: 0.9 }],
      sell_votes: [],
      agreement: 0.85,
    },
  },
  leaderboard: [['TechAgent', 5.4], ['MomentumAgent', 3.2]],
  trades_today: [
    { agent: 'TechAgent', symbol: 'AAPL', action: 'BUY', shares: 10, price: 180, pnl: null, timestamp: '15:30', reasoning: 'momentum' },
  ],
  scanner_recs: [],
}

describe('SummaryPanelV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => sampleSummary,
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the summary header', async () => {
    render(<SummaryPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/DAILY ROLL-UP/i)).toBeInTheDocument()
    })
  })

  it('renders the AI narrative when present', async () => {
    render(<SummaryPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/Markets rallied on Fed dovish tone/i)).toBeInTheDocument()
    })
  })

  it('renders the leaderboard ranking', async () => {
    render(<SummaryPanelV2 />)
    await waitFor(() => {
      // TechAgent appears in the leaderboard, agent breakdown header, etc.
      expect(screen.getAllByText(/TechAgent/i).length).toBeGreaterThanOrEqual(1)
    })
  })
})
