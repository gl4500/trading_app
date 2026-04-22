import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ScannerPanelV2 from '../ScannerPanelV2'

const sampleScan = {
  status: 'ok',
  scanned_at: '2026-04-21T15:00:00Z',
  recommendations: [
    {
      symbol: 'NVDA',
      action: 'BUY',
      confidence: 0.85,
      reasoning: 'Strong momentum + AI tailwind',
      composite_score: 0.55,
      price_target: 950,
      stop_loss_pct: 5,
      catalysts: ['Earnings beat', 'New product launch'],
      timestamp: '2026-04-21T15:00:00Z',
    },
  ],
  candidates: [
    { symbol: 'AMD',  price: 165.5, pct_change: 3.2, vol_ratio: 2.1, momentum_score: 0.7 },
    { symbol: 'TSLA', price: 230.0, pct_change: 1.8, vol_ratio: 1.5, momentum_score: 0.5 },
  ],
}

describe('ScannerPanelV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => sampleScan,
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the scanner header', async () => {
    render(<ScannerPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/SCANNER/i)).toBeInTheDocument()
    })
  })

  it('renders recommendation rows when scan returns recommendations', async () => {
    render(<ScannerPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText('NVDA')).toBeInTheDocument()
    })
    // BUY appears in row + possibly a header pill — just assert it shows
    expect(screen.getAllByText('BUY').length).toBeGreaterThanOrEqual(1)
  })

  it('shows the empty state when no scan results are returned', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'no_scan', recommendations: [], candidates: [] }),
    }))
    render(<ScannerPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/NO SCAN RESULTS/i)).toBeInTheDocument()
    })
  })
})
