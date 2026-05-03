import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import DriftV2 from '../DriftV2'

const allClearResponse = {
  reports: [],
  drifting_agents: 0,
  all_clear: true,
}

const driftingResponse = {
  reports: [
    {
      agent_name: 'TechAgent',
      is_drifting: false,
      message: 'Within baseline.',
    },
    {
      agent_name: 'MomentumAgent',
      is_drifting: true,
      message: 'Win rate dropped 18%',
      current_win_rate: 0.32,
      baseline_win_rate: 0.50,
    },
  ],
  drifting_agents: 1,
  all_clear: false,
}

describe('DriftV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => allClearResponse,
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders ALL CLEAR when all_clear is true', async () => {
    render(<DriftV2 />)
    await waitFor(() => {
      expect(screen.getByText(/ALL CLEAR/i)).toBeInTheDocument()
    })
  })

  it('renders drift count and DRIFT pill when an agent is drifting', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => driftingResponse,
    }))
    render(<DriftV2 />)
    await waitFor(() => {
      expect(screen.getByText(/1 AGENT/i)).toBeInTheDocument()
    })
    // DRIFT pill on the drifting row
    expect(screen.getAllByText(/\bDRIFT\b/).length).toBeGreaterThanOrEqual(1)
    // OK pill on the clean row
    expect(screen.getAllByText(/\bOK\b/).length).toBeGreaterThanOrEqual(1)
    // Agent names
    expect(screen.getByText(/TechAgent/)).toBeInTheDocument()
    expect(screen.getByText(/MomentumAgent/)).toBeInTheDocument()
  })

  it('renders grouped numeric columns with base/now/delta values', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        reports: [{
          agent_name: 'ClaudeAgent',
          is_drifting: true,
          alerts: ['Win rate dropped 14.9pp'],
          baseline_win_rate: 55.2,
          recent_win_rate: 40.3,
          win_rate_change: -14.9,
          baseline_avg_pnl_pct: 0.85,
          recent_avg_pnl_pct: 0.12,
          avg_pnl_change: -0.73,
          total_trades: 32,
          recent_window: 20,
        }],
        drifting_agents: 1,
        all_clear: false,
      }),
    }))
    render(<DriftV2 />)
    await waitFor(() => {
      expect(screen.getByText(/ClaudeAgent/)).toBeInTheDocument()
    })
    // Grouped headers
    expect(screen.getByText(/Win Rate %/i)).toBeInTheDocument()
    expect(screen.getByText(/Avg P&L %/i)).toBeInTheDocument()
    // Numeric cells appear in their own columns
    expect(screen.getByText(/55\.2%/)).toBeInTheDocument()
    expect(screen.getByText(/40\.3%/)).toBeInTheDocument()
    expect(screen.getByText(/-14\.9/)).toBeInTheDocument()
    expect(screen.getByText(/0\.85%/)).toBeInTheDocument()
    expect(screen.getByText(/0\.12%/)).toBeInTheDocument()
    expect(screen.getByText(/-0\.73/)).toBeInTheDocument()
    // Trade counts
    expect(screen.getByText(/^32$/)).toBeInTheDocument()
    expect(screen.getByText(/^20$/)).toBeInTheDocument()
    // Alerts row
    expect(screen.getByText(/Win rate dropped 14\.9pp/)).toBeInTheDocument()
  })

  it('refetches on refresh click', async () => {
    render(<DriftV2 />)
    await waitFor(() => {
      expect(screen.getByText(/ALL CLEAR/i)).toBeInTheDocument()
    })
    const fetchMock = (globalThis as any).fetch as ReturnType<typeof vi.fn>
    const before = fetchMock.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: /refresh/i }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(before)
    })
  })
})
