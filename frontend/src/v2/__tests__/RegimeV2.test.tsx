import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import RegimeV2 from '../RegimeV2'

const sampleRegime = {
  regime: {
    state: 'RISK_ON',
    score: 0.42,
    trend: 'UP',
    volatility: 0.18,
    breadth: 0.61,
    updated: '2026-04-21T10:00:00Z',
  },
}

describe('RegimeV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => sampleRegime,
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows loading placeholder before fetch resolves', async () => {
    let resolveFetch: (v: any) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise(r => { resolveFetch = r })))
    render(<RegimeV2 />)
    expect(screen.getByText(/LOADING REGIME/i)).toBeInTheDocument()
    resolveFetch({ ok: true, json: async () => sampleRegime })
  })

  it('renders regime fields when populated', async () => {
    render(<RegimeV2 />)
    await waitFor(() => {
      expect(screen.getByText(/RISK_ON/)).toBeInTheDocument()
    })
    // score 0.42 should appear somewhere
    expect(screen.getByText(/0\.42/)).toBeInTheDocument()
    // trend
    expect(screen.getByText(/\bUP\b/)).toBeInTheDocument()
  })

  it('refetches regime on refresh button click', async () => {
    render(<RegimeV2 />)
    await waitFor(() => {
      expect(screen.getByText(/RISK_ON/)).toBeInTheDocument()
    })
    const fetchMock = (globalThis as any).fetch as ReturnType<typeof vi.fn>
    const callsBefore = fetchMock.mock.calls.length
    const refreshBtn = screen.getByRole('button', { name: /refresh/i })
    fireEvent.click(refreshBtn)
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore)
    })
  })

  it('shows error state when fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({}),
    }))
    render(<RegimeV2 />)
    await waitFor(() => {
      expect(screen.getByText(/REGIME UNAVAILABLE/i)).toBeInTheDocument()
    })
  })
})
