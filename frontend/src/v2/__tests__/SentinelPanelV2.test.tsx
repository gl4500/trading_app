import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import SentinelPanelV2 from '../SentinelPanelV2'

const sampleSentinel = {
  market_status: 'closed',
  market_is_open: false,
  minutes_until_open: 75,
  last_poll: '2026-04-21T14:00:00Z',
  catalyst_count: 2,
  catalysts: [
    {
      headline: 'Fed signals rate cut',
      summary: 'Powell suggests Sep cut',
      score: 4,
      category: 'policy',
      sectors: ['banks'],
      detected_at: '2026-04-21T13:55:00Z',
    },
    {
      symbol: 'NVDA',
      headline: 'NVDA earnings beat',
      score: 5,
      category: 'catalyst',
      detected_at: '2026-04-21T13:30:00Z',
    },
  ],
}

const sampleImpact = {
  total: 1,
  confirmed: [
    {
      symbol: 'NVDA',
      headline: 'NVDA earnings beat',
      score: 5,
      category: 'catalyst',
      price_at: 900.0,
      detected_at: '2026-04-21T13:30:00Z',
      during_session: false,
      price_open: 920.0,
      price_1h: 935.0,
      change_open: 2.22,
      change_1h: 3.89,
    },
  ],
  pending: [],
}

describe('SentinelPanelV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/sentinel')) {
        return Promise.resolve({ ok: true, json: async () => sampleSentinel })
      }
      if (typeof url === 'string' && url.includes('/api/news-impact')) {
        return Promise.resolve({ ok: true, json: async () => sampleImpact })
      }
      return Promise.resolve({ ok: true, json: async () => ({}) })
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the sentinel header', async () => {
    render(<SentinelPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/SENTINEL/i)).toBeInTheDocument()
    })
  })

  it('renders catalyst entries when sentinel returns data', async () => {
    render(<SentinelPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/Fed signals rate cut/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/NVDA earnings beat/i)).toBeInTheDocument()
  })

  it('shows the empty state when no catalysts are returned', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        market_status: 'closed',
        market_is_open: false,
        minutes_until_open: 0,
        last_poll: null,
        catalyst_count: 0,
        catalysts: [],
      }),
    }))
    render(<SentinelPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/NO CATALYSTS DETECTED/i)).toBeInTheDocument()
    })
  })
})
