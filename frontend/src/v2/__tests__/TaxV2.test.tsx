import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TaxV2 from '../TaxV2'

const currentYear = new Date().getFullYear()
const previousYear = currentYear - 1

const samplePayload = {
  year: currentYear,
  short_term_gain: 5000.0,
  short_term_loss: 1500.0,
  short_term_net: 3500.0,
  long_term_gain: 12000.0,
  long_term_loss: 2000.0,
  long_term_net: 10000.0,
  wash_sale_count: 0,
  quarterly_net: { Q1: 1000.0, Q2: 2000.0, Q3: 3500.0, Q4: 7000.0 },
  total_net: 13500.0,
}

describe('TaxV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => samplePayload,
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows loading placeholder before fetch resolves', () => {
    let resolveFetch: (v: any) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise(r => { resolveFetch = r })))
    render(<TaxV2 />)
    expect(screen.getByText(/LOADING TAX ESTIMATE/i)).toBeInTheDocument()
    resolveFetch({ ok: true, json: async () => samplePayload })
  })

  it('renders total net and quarterly tiles when populated', async () => {
    render(<TaxV2 />)
    await waitFor(() => {
      expect(screen.getByText(/TAX ESTIMATE/i)).toBeInTheDocument()
    })
    // Total net dollar amount appears
    expect(screen.getAllByText(/\+\$13,500\.00/).length).toBeGreaterThanOrEqual(1)
    // At least one quarter labelled Q1
    expect(screen.getAllByText(/^Q1$/).length).toBeGreaterThanOrEqual(1)
    // Q1 value
    expect(screen.getAllByText(/\+\$1,000\.00/).length).toBeGreaterThanOrEqual(1)
  })

  it('refetches with new year when year selector changes', async () => {
    const user = userEvent.setup()
    render(<TaxV2 />)
    await waitFor(() => {
      expect(screen.getByText(/TAX ESTIMATE/i)).toBeInTheDocument()
    })
    const fetchMock = (globalThis as any).fetch as ReturnType<typeof vi.fn>
    const select = screen.getByLabelText(/year/i) as HTMLSelectElement
    await user.selectOptions(select, String(previousYear))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringContaining(`year=${previousYear}`),
      )
    })
  })

  it('shows alpaca unavailable message on 503', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: { error: 'alpaca_unavailable' } }),
    }))
    render(<TaxV2 />)
    await waitFor(() => {
      expect(screen.getByText(/ALPACA UNAVAILABLE/i)).toBeInTheDocument()
    })
  })
})
