import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import App from '../App'

// Session expiry with the REAL legacy Dashboard — the default UI (no ?v=2).
// The operator scenario: logged in, dashboard up, backend restarts, then the
// next panel request (here the legacy Signals tab) gets 401.

class FakeWebSocket {
  static OPEN = 1
  readyState = 0
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((e: unknown) => void) | null = null
  onerror: (() => void) | null = null
  constructor(_url: string) {}
  send() {}
  close() {}
  addEventListener() {}
}

function jsonResponse(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

describe('App session expiry with the legacy Dashboard (default UI)', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    window.history.replaceState(null, '', '/')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('returns to the login page when a legacy panel request gets 401 after login', async () => {
    let sessionAlive = true
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.includes('/api/auth/check')) return jsonResponse(200, { authenticated: true })
      if (!sessionAlive) return jsonResponse(401, { detail: 'Authentication required' })
      if (url.includes('/api/trades')) return jsonResponse(200, { trades: [] })
      if (url.includes('/api/benchmarks')) {
        return jsonResponse(200, {
          period_days: 30, as_of: '2026-10-17', spy_return_pct: 1.0, dji_return_pct: 0.5, agents: [],
        })
      }
      return jsonResponse(200, {})
    }))

    render(<App />)

    // Real legacy Dashboard is up.
    const signalsTab = await screen.findByRole('button', { name: /Signals ✦/ })
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()

    // Backend restarts: the in-memory session is gone.
    sessionAlive = false
    fireEvent.click(signalsTab)

    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Signals ✦/ })).not.toBeInTheDocument()
  })
})
