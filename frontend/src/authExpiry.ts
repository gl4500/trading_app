// Session-expiry detection.
//
// The backend keeps sessions in memory, so after a restart or the 24 h TTL every
// /api call answers 401. This module wraps window.fetch once and tells
// subscribers when an authenticated same-origin /api request comes back 401, so
// the app can return to the login page instead of leaving every panel broken.
//
// Auth generations: each successful login (or startup session check) begins a
// new generation. A request remembers the generation it STARTED in, and its 401
// only counts if that generation is still current — so a slow request from the
// previous session cannot log the user out again right after they re-login.

type AuthExpiredListener = () => void

// Endpoints whose 401 is part of the login flow itself, not an expired session.
const AUTH_FLOW_PATHS: ReadonlySet<string> = new Set([
  '/api/login',
  '/api/logout',
  '/api/auth/check',
])
const LOGIN_PATH = '/api/login'

const WRAPPED_MARKER = '__authExpiryWrapped__'
const UNAUTHORIZED = 401

const listeners = new Set<AuthExpiredListener>()
let authGeneration = 0

function rawUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.href
  return input.url
}

/** The request's pathname when it targets this page's origin, else null. */
function sameOriginPath(input: RequestInfo | URL): string | null {
  try {
    const page = new URL(window.location.href)
    const target = new URL(rawUrl(input), page)
    return target.origin === page.origin ? target.pathname : null
  } catch {
    return null
  }
}

export function isSessionExpiry(input: RequestInfo | URL, status: number): boolean {
  if (status !== UNAUTHORIZED) return false
  const path = sameOriginPath(input)
  return path !== null && path.startsWith('/api/') && !AUTH_FLOW_PATHS.has(path)
}

function isSuccessfulLogin(input: RequestInfo | URL, response: Response): boolean {
  return response.ok && sameOriginPath(input) === LOGIN_PATH
}

/** Begin a new auth generation: 401s from requests started earlier are ignored. */
export function markAuthenticated(): void {
  authGeneration += 1
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
    const startedIn = authGeneration
    const response = await current.call(window, input, init)
    if (isSuccessfulLogin(input, response)) markAuthenticated()
    else if (startedIn === authGeneration && isSessionExpiry(input, response.status)) notifyAuthExpired()
    return response
  }
  Object.defineProperty(wrapped, WRAPPED_MARKER, { value: true })
  window.fetch = wrapped
}
