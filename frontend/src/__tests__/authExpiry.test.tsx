import React, { useEffect, useState } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { installAuthExpiryFetch, onAuthExpired, isSessionExpiry, markAuthenticated } from '../authExpiry'

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

// ── Codex review PR #114 ────────────────────────────────────────────────────

interface Deferred { resolve: (r: Response) => void; url: string }

function respond(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('App: a stale 401 from the previous session after re-login', () => {
  beforeEach(() => { vi.stubGlobal('WebSocket', FakeWebSocket) })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('keeps the dashboard for an old-session 401, but logs out on a new-session 401', async () => {
    const pendingTrades: Deferred[] = []
    let signalsCalls = 0
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.includes('/api/auth/check')) return Promise.resolve(respond(200, { authenticated: true }))
      if (url.includes('/api/login')) return Promise.resolve(respond(200, { ok: true }))
      if (url.includes('/api/trades')) {
        return new Promise<Response>(resolve => { pendingTrades.push({ resolve, url }) })
      }
      if (url.includes('/api/signals')) {
        signalsCalls += 1
        return Promise.resolve(signalsCalls === 1 ? respond(401) : respond(200, { signals: {} }))
      }
      return Promise.resolve(respond(200))
    }))

    render(<App />)

    // Old session: /api/trades (A) is still in flight when /api/signals gets 401.
    const password = await screen.findByLabelText('Password')
    expect(pendingTrades).toHaveLength(1)

    fireEvent.change(password, { target: { value: 'hunter2' } })
    fireEvent.click(screen.getByRole('button', { name: /Sign In/ }))
    await screen.findByText(/FAKE DASHBOARD · 200/)
    await waitFor(() => expect(pendingTrades).toHaveLength(2))   // B started under the new session

    // A (started before the re-login) now answers 401 — must be ignored.
    pendingTrades[0].resolve(respond(401))
    await new Promise(r => setTimeout(r, 20))
    expect(screen.getByText(/FAKE DASHBOARD · 200/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()

    // B (started under the new session) answers 401 — that session is gone too.
    pendingTrades[1].resolve(respond(401))
    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
  })
})

describe('authExpiry generations', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function deferredFetch() {
    const pending: Deferred[] = []
    vi.stubGlobal('fetch', vi.fn().mockImplementation((input: string) => {
      if (input.startsWith('/api/login')) return Promise.resolve(respond(200))
      return new Promise<Response>(resolve => { pending.push({ resolve, url: input }) })
    }))
    installAuthExpiryFetch()
    return pending
  }

  it('ignores a 401 from a request started before markAuthenticated()', async () => {
    const pending = deferredFetch()
    const listener = vi.fn()
    const unsubscribe = onAuthExpired(listener)

    const old = window.fetch('/api/signals')
    markAuthenticated()
    const fresh = window.fetch('/api/trades')

    pending[0].resolve(respond(401))
    await old
    expect(listener).not.toHaveBeenCalled()

    pending[1].resolve(respond(401))
    await fresh
    expect(listener).toHaveBeenCalledTimes(1)
    unsubscribe()
  })

  it('a successful /api/login through fetch also starts a new generation', async () => {
    const pending = deferredFetch()
    const listener = vi.fn()
    const unsubscribe = onAuthExpired(listener)

    const old = window.fetch('/api/signals')
    await window.fetch('/api/login', { method: 'POST' })
    pending[0].resolve(respond(401))
    await old
    expect(listener).not.toHaveBeenCalled()
    unsubscribe()
  })
})

describe('isSessionExpiry origin and path scope', () => {
  const here = () => window.location.origin

  it.each([
    ['relative path', () => '/api/signals'],
    ['same-origin absolute string', () => `${here()}/api/signals`],
    ['same-origin URL object', () => new URL('/api/signals', window.location.href)],
    ['same-origin Request object', () => new Request(`${here()}/api/signals`)],
  ])('counts a 401 from a %s', (_label, input) => {
    expect(isSessionExpiry(input(), 401)).toBe(true)
  })

  it.each([
    ['foreign-origin string', () => 'https://other.example/api/resource'],
    ['foreign-origin URL object', () => new URL('https://other.example/api/resource')],
    ['foreign-origin Request object', () => new Request('https://other.example/api/resource')],
    ['protocol-relative URL', () => '//other.example/api/x'],
    ['auth check with query', () => '/api/auth/check?x=1'],
    ['login with query', () => '/api/login?next=/'],
    ['logout', () => '/api/logout'],
    ['non-api path', () => '/static/app.js'],
  ])('does not count a 401 from a %s', (_label, input) => {
    expect(isSessionExpiry(input(), 401)).toBe(false)
  })

  it.each([400, 403, 404, 500, 200])('never counts status %i', status => {
    expect(isSessionExpiry('/api/signals', status)).toBe(false)
  })

  it('does not notify for a foreign-origin 401 through the wrapper', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(401)))
    installAuthExpiryFetch()
    const listener = vi.fn()
    const unsubscribe = onAuthExpired(listener)
    await window.fetch('https://other.example/api/resource')
    await window.fetch('//other.example/api/x')
    expect(listener).not.toHaveBeenCalled()
    unsubscribe()
    vi.unstubAllGlobals()
  })
})
