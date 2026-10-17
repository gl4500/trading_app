import React, { useEffect, useState } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { installAuthExpiryFetch, onAuthExpired } from '../authExpiry'

// The dashboard is replaced by a stand-in "panel" that issues one /api request
// on mount, so these tests exercise App's auth flow without the real panels.
vi.mock('../components/Dashboard', () => ({
  default: function FakeDashboard() {
    const [status, setStatus] = useState<string>('pending')
    useEffect(() => {
      fetch('/api/signals')
        .then(r => setStatus(String(r.status)))
        .catch(() => setStatus('threw'))
    }, [])
    return <div>FAKE DASHBOARD · {status}</div>
  },
}))

import App from '../App'

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

type Responder = (url: string) => { status: number; body?: unknown }

function stubFetch(respond: Responder) {
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const { status, body = {} } = respond(url)
    return Promise.resolve(new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }))
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('App session expiry', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('returns to the login page when a panel request gets 401 after login, then recovers after re-login', async () => {
    let signalsCalls = 0
    stubFetch(url => {
      if (url.includes('/api/auth/check')) return { status: 200, body: { authenticated: true } }
      if (url.includes('/api/login')) return { status: 200, body: { ok: true } }
      if (url.includes('/api/signals')) {
        signalsCalls += 1
        return signalsCalls === 1
          ? { status: 401, body: { detail: 'Authentication required' } }
          : { status: 200, body: { signals: {} } }
      }
      return { status: 200, body: {} }
    })

    render(<App />)

    const password = await screen.findByLabelText('Password')
    expect(screen.queryByText(/FAKE DASHBOARD/)).not.toBeInTheDocument()

    fireEvent.change(password, { target: { value: 'hunter2' } })
    fireEvent.click(screen.getByRole('button', { name: /Sign In/ }))

    expect(await screen.findByText(/FAKE DASHBOARD · 200/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  it('does not log the user out on a non-401 error (500)', async () => {
    stubFetch(url => {
      if (url.includes('/api/auth/check')) return { status: 200 }
      if (url.includes('/api/signals')) return { status: 500, body: { detail: 'boom' } }
      return { status: 200 }
    })

    render(<App />)

    expect(await screen.findByText(/FAKE DASHBOARD · 500/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  it('shows the login page when /api/auth/check returns 401 at startup', async () => {
    const fetchFn = stubFetch(url => {
      if (url.includes('/api/auth/check')) return { status: 401, body: { detail: 'Authentication required' } }
      return { status: 200 }
    })

    render(<App />)

    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
    expect(screen.queryByText(/FAKE DASHBOARD/)).not.toBeInTheDocument()
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })
})

describe('installAuthExpiryFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('wraps fetch only once, notifies on /api 401 and passes every response through untouched', async () => {
    const responses: Record<string, Response> = {}
    const inner = vi.fn().mockImplementation((input: string) => {
      const status = input.includes('expired') || input.includes('/api/login') ? 401
        : input.includes('broken') ? 500 : 200
      const res = new Response('{}', { status })
      responses[input] = res
      return Promise.resolve(res)
    })
    vi.stubGlobal('fetch', inner)

    installAuthExpiryFetch()
    const wrappedOnce = window.fetch
    installAuthExpiryFetch()
    expect(window.fetch).toBe(wrappedOnce)
    expect(window.fetch).not.toBe(inner)

    const listener = vi.fn()
    const unsubscribe = onAuthExpired(listener)

    const expired = await window.fetch('/api/expired')
    expect(expired).toBe(responses['/api/expired'])
    expect(listener).toHaveBeenCalledTimes(1)
    expect(inner).toHaveBeenCalledTimes(1)

    const login = await window.fetch('/api/login', { method: 'POST' })
    expect(login.status).toBe(401)
    expect(listener).toHaveBeenCalledTimes(1)

    const broken = await window.fetch('/api/broken')
    expect(broken).toBe(responses['/api/broken'])
    expect(broken.status).toBe(500)
    expect(listener).toHaveBeenCalledTimes(1)

    unsubscribe()
    await window.fetch('/api/expired')
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('propagates a rejected fetch without notifying', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    installAuthExpiryFetch()
    const listener = vi.fn()
    const unsubscribe = onAuthExpired(listener)
    await expect(window.fetch('/api/anything')).rejects.toThrow('Failed to fetch')
    expect(listener).not.toHaveBeenCalled()
    unsubscribe()
  })
})
