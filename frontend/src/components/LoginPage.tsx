import React, { useState, useRef, useEffect } from 'react'

interface LoginPageProps {
  onLogin: () => void
}

export default function LoginPage({ onLogin }: LoginPageProps) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!password) return

    setLoading(true)
    setError('')

    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })

      if (res.ok) {
        onLogin()
      } else if (res.status === 429) {
        setError('Too many attempts. Wait 5 minutes and try again.')
      } else {
        setError('Incorrect password.')
        setPassword('')
        inputRef.current?.focus()
      }
    } catch {
      setError('Cannot reach server. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="text-4xl mb-3">🤖</div>
          <h1 className="text-xl font-bold text-white">AI Trading Competition</h1>
          <p className="text-sm text-gray-400 mt-1">Enter your password to continue</p>
        </div>

        {/* Card */}
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 shadow-2xl">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="password" className="block text-xs font-medium text-gray-400 mb-1.5">
                Password
              </label>
              <input
                ref={inputRef}
                id="password"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                disabled={loading}
                autoComplete="current-password"
                className={`w-full bg-gray-900 border rounded-lg px-3 py-2.5 text-sm text-white
                  placeholder-gray-600 outline-none transition-colors
                  focus:border-blue-500 focus:ring-1 focus:ring-blue-500
                  disabled:opacity-50
                  ${error ? 'border-red-500' : 'border-gray-600'}`}
                placeholder="••••••••••••"
              />
            </div>

            {error && (
              <p className="text-xs text-red-400 flex items-center gap-1.5">
                <span>⚠</span>
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !password}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40
                disabled:cursor-not-allowed text-white text-sm font-medium
                py-2.5 rounded-lg transition-colors"
            >
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-600 mt-4">
          Set <code className="text-gray-500">APP_PASSWORD</code> in <code className="text-gray-500">.env</code> to change
        </p>
      </div>
    </div>
  )
}
