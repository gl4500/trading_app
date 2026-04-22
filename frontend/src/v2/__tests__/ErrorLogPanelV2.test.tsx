import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ErrorLogPanelV2 from '../ErrorLogPanelV2'

const sampleEntries = {
  entries: [
    {
      timestamp: '2026-04-21T15:30:00Z',
      level: 'ERROR',
      logger: 'agents.tech_agent',
      message: 'Failed to fetch indicators for AAPL',
    },
    {
      timestamp: '2026-04-21T15:31:00Z',
      level: 'WARNING',
      logger: 'data.market_data',
      message: 'Rate limit approaching',
    },
  ],
}

describe('ErrorLogPanelV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => sampleEntries,
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the error log header', async () => {
    render(<ErrorLogPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/ERROR LOG/i)).toBeInTheDocument()
    })
  })

  it('renders entries with their messages and loggers', async () => {
    render(<ErrorLogPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/Failed to fetch indicators for AAPL/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/Rate limit approaching/i)).toBeInTheDocument()
  })

  it('shows the empty state when there are no entries', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ entries: [] }),
    }))
    render(<ErrorLogPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/NO LOG ENTRIES/i)).toBeInTheDocument()
    })
  })
})
