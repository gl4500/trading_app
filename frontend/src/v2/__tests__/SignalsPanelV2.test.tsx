import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import SignalsPanelV2 from '../SignalsPanelV2'

const sampleSignals = {
  AAPL: {
    symbol: 'AAPL',
    composite_score: 0.42,
    confidence: 0.78,
    verdict: 'STRONG BUY (high conviction)',
    sources: {
      analyst_consensus: { score: 0.5, weight: 0.35, bull: 8, hold: 2, bear: 1, total: 11, price_target: 220 },
      earnings_surprise: { score: 0.3, weight: 0.22, surprise_pct: 12.5 },
      alpaca_news:       { score: 0.2, weight: 0.18, articles: 14 },
      yahoo_news:        { score: 0.4, weight: 0.12, articles: 6 },
      congressional_trades: { score: 0.1, weight: 0.13, congress_buys: 2, congress_sells: 0, congress_total: 2, total_filings: 5 },
    },
    yahoo_news_headlines: ['AAPL beats expectations', 'Strong iPhone demand'],
  },
}

describe('SignalsPanelV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ signals: sampleSignals }),
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the panel header', async () => {
    render(<SignalsPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/SIGNAL BOARD/i)).toBeInTheDocument()
    })
  })

  it('shows an empty state when no signals are returned', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ signals: {} }),
    }))
    render(<SignalsPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/NO SIGNAL DATA/i)).toBeInTheDocument()
    })
  })

  it('renders signal rows with symbol and composite score when data is present', async () => {
    render(<SignalsPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText('AAPL')).toBeInTheDocument()
    })
    // composite +0.42 may also appear in AVG; assert at least one match
    expect(screen.getAllByText(/\+0\.42/).length).toBeGreaterThanOrEqual(1)
    // verdict label appears in the row
    expect(screen.getByText(/STRONG BUY/i)).toBeInTheDocument()
  })
})
