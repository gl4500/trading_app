import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import TokensPanelV2 from '../TokensPanelV2'

const sampleLog = {
  entries: [
    {
      id: 1,
      date: '2026-04-21',
      timestamp: '2026-04-21T15:30:00Z',
      agent: 'ClaudeAgent',
      model: 'claude-opus-4-7',
      prompt_tokens: 1200,
      completion_tokens: 300,
      total_tokens: 1500,
      daily_total: 25000,
      daily_limit: 100000,
      limit_hit: false,
    },
  ],
}

const sampleStats = {
  agents: {
    ClaudeAgent: {
      daily_tokens: 25000,
      session_tokens: 5000,
      calls_this_hour: 10,
      hourly_call_limit: 60,
      daily_limit: 100000,
      daily_remaining: 75000,
    },
  },
  totals: { daily_tokens: 25000, session_tokens: 5000 },
}

describe('TokensPanelV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/token-log')) {
        return Promise.resolve({ ok: true, json: async () => sampleLog })
      }
      if (typeof url === 'string' && url.includes('/api/tokens')) {
        return Promise.resolve({ ok: true, json: async () => sampleStats })
      }
      return Promise.resolve({ ok: true, json: async () => ({}) })
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the tokens panel header', async () => {
    render(<TokensPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/TOKEN LOG/i)).toBeInTheDocument()
    })
  })

  it('renders log entries when data is returned', async () => {
    render(<TokensPanelV2 />)
    await waitFor(() => {
      // ClaudeAgent appears in the filter dropdown + the log table — assert at least one match
      expect(screen.getAllByText(/ClaudeAgent/).length).toBeGreaterThanOrEqual(1)
    })
    expect(screen.getByText('claude-opus-4-7')).toBeInTheDocument()
  })

  it('shows the empty state when no entries are returned', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (typeof url === 'string' && url.includes('/api/token-log')) {
        return Promise.resolve({ ok: true, json: async () => ({ entries: [] }) })
      }
      return Promise.resolve({ ok: true, json: async () => ({ agents: {}, totals: { daily_tokens: 0, session_tokens: 0 } }) })
    }))
    render(<TokensPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/NO TOKEN LOG ENTRIES/i)).toBeInTheDocument()
    })
  })
})
