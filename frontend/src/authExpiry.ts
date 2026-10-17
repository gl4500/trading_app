// Session-expiry detection.
//
// The backend keeps sessions in memory, so after a restart or the 24 h TTL every
// /api call answers 401. This module wraps window.fetch once and tells
// subscribers when an authenticated /api request comes back 401, so the app can
// return to the login page instead of leaving every panel broken.

type AuthExpiredListener = () => void

// Endpoints whose 401 is part of the login flow itself, not an expired session.
const AUTH_FLOW_PATHS: ReadonlySet<string> = new Set([
  '/api/login',
  '/api/logout',
  '/api/auth/check',
])

const WRAPPED_MARKER = '__authExpiryWrapped__'
const UNAUTHORIZED = 401

const listeners = new Set<AuthExpiredListener>()

function requestPath(input: RequestInfo | URL): string | null {
  const raw = typeof input === 'string' ? input
    : input instanceof URL ? input.href
    : input.url
  try {
    return new URL(raw, window.location.href).pathname
  } catch {
    return null
  }
}

export function isSessionExpiry(input: RequestInfo | URL, status: number): boolean {
  if (status !== UNAUTHORIZED) return false
  const path = requestPath(input)
  return path !== null && path.startsWith('/api/') && !AUTH_FLOW_PATHS.has(path)
}

function notifyAuthExpired(): void {
  listeners.forEach(listener => listener())
}

/** Subscribe to session-expiry events. Returns the unsubscribe function. */
export function onAuthExpired(listener: AuthExpiredListener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** Wrap window.fetch so expired sessions are reported. Safe to call repeatedly. */
export function installAuthExpiryFetch(): void {
  const current = window.fetch as typeof window.fetch & { [WRAPPED_MARKER]?: boolean }
  if (typeof current !== 'function' || current[WRAPPED_MARKER]) return

  const wrapped = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const response = await current.call(window, input, init)
    if (isSessionExpiry(input, response.status)) notifyAuthExpired()
    return response
  }
  Object.defineProperty(wrapped, WRAPPED_MARKER, { value: true })
  window.fetch = wrapped
}
