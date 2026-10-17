import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import SignalsPanelV2 from '../SignalsPanelV2'
import ScannerPanelV2 from '../ScannerPanelV2'
import SummaryPanelV2 from '../SummaryPanelV2'
import SentinelPanelV2 from '../SentinelPanelV2'
import TokensPanelV2 from '../TokensPanelV2'
import ErrorLogPanelV2 from '../ErrorLogPanelV2'
// Legacy panels — still the default UI (rendered by components/Dashboard without ?v=2).
import SignalsPanel from '../../components/SignalsPanel'
import ScannerPanel from '../../components/ScannerPanel'
import SummaryPanel from '../../components/SummaryPanel'
import SentinelPanel from '../../components/SentinelPanel'
import TokensPanel from '../../components/TokensPanel'
import ErrorLogPanel from '../../components/ErrorLogPanel'

// Every data panel (V2 and the legacy default UI) must surface a failed main request (non-OK status or a
// thrown fetch) as a visible message, and clear it after a successful refresh.

type Mode = 'http500' | 'reject' | 'ok'

const OK_BODIES: Array<[string, unknown]> = [
  ['/api/signals', { signals: {} }],
  ['/api/scanner', { status: 'ok', scanned_at: '2026-04-21T15:00:00Z', recommendations: [], candidates: [] }],
  ['/api/summary', {
    status: 'ok', generated_at: '2026-04-21T15:00:00Z', date: '2026-04-21', market_status: 'open',
    narrative: 'calm day', agent_summaries: {}, consensus: {}, leaderboard: [], trades_today: [], scanner_recs: [],
  }],
  ['/api/sentinel', { market_status: 'closed', market_is_open: false, catalyst_count: 0, catalysts: [] }],
  ['/api/news-impact', { total: 0, confirmed: [], pending: [] }],
  ['/api/token-log', { entries: [] }],
  ['/api/errors', { entries: [] }],
]

function okBodyFor(url: string): unknown {
  const hit = OK_BODIES.find(([prefix]) => url.includes(prefix))
  return hit ? hit[1] : {}
}

let mode: Mode = 'ok'

function installFetch() {
  vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
    if (mode === 'reject') return Promise.reject(new TypeError('Failed to fetch'))
    if (mode === 'http500') {
      return Promise.resolve({ ok: false, status: 500, json: async () => ({ detail: 'boom' }) })
    }
    // /api/tokens (stats) is a side request; keep it failing quietly so only
    // the main request's outcome decides what the panel shows.
    if (url.includes('/api/tokens')) return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
    return Promise.resolve({ ok: true, status: 200, json: async () => okBodyFor(url) })
  }))
}

interface PanelCase {
  name: string
  Component: React.ComponentType
  refreshButton: RegExp
}

const PANELS: PanelCase[] = [
  { name: 'SignalsPanelV2',  Component: SignalsPanelV2,  refreshButton: /↻/ },
  { name: 'ScannerPanelV2',  Component: ScannerPanelV2,  refreshButton: /RUN SCAN/ },
  { name: 'SummaryPanelV2',  Component: SummaryPanelV2,  refreshButton: /REFRESH/ },
  { name: 'SentinelPanelV2', Component: SentinelPanelV2, refreshButton: /REFRESH/ },
  { name: 'TokensPanelV2',   Component: TokensPanelV2,   refreshButton: /REFRESH/ },
  { name: 'ErrorLogPanelV2', Component: ErrorLogPanelV2, refreshButton: /⟳ REFRESH/ },
  { name: 'legacy SignalsPanel',  Component: SignalsPanel,  refreshButton: /↻/ },
  { name: 'legacy ScannerPanel',  Component: ScannerPanel,  refreshButton: /Run Scan/ },
  { name: 'legacy SummaryPanel',  Component: SummaryPanel,  refreshButton: /Refresh/ },
  { name: 'legacy SentinelPanel', Component: SentinelPanel, refreshButton: /Refresh/ },
  { name: 'legacy TokensPanel',   Component: TokensPanel,   refreshButton: /⟳ Refresh/ },
  { name: 'legacy ErrorLogPanel', Component: ErrorLogPanel, refreshButton: /⟳ Refresh/ },
]

const THROWN = /Failed to fetch|backend offline/i
const ANY_FAILURE = /HTTP 500|Failed to fetch|backend offline/i

describe.each(PANELS)('$name request-failure messaging', ({ Component, refreshButton }) => {
  beforeEach(() => { installFetch() })

  afterEach(() => {
    mode = 'ok'
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows a visible error including the HTTP status when the request returns 500', async () => {
    mode = 'http500'
    render(<Component />)
    expect(await screen.findByText(/HTTP 500/)).toBeInTheDocument()
  })

  it('shows a visible error when the request throws', async () => {
    mode = 'reject'
    render(<Component />)
    expect(await screen.findByText(THROWN)).toBeInTheDocument()
  })

  it('clears the 500 error after a successful refresh', async () => {
    mode = 'http500'
    render(<Component />)
    await screen.findByText(/HTTP 500/)
    mode = 'ok'
    fireEvent.click(await screen.findByRole('button', { name: refreshButton }))
    await waitFor(() => expect(screen.queryByText(ANY_FAILURE)).not.toBeInTheDocument())
  })

  it('clears the thrown-request error after a successful refresh', async () => {
    mode = 'reject'
    render(<Component />)
    await screen.findByText(THROWN)
    mode = 'ok'
    fireEvent.click(await screen.findByRole('button', { name: refreshButton }))
    await waitFor(() => expect(screen.queryByText(ANY_FAILURE)).not.toBeInTheDocument())
  })
})
