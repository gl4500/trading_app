import React, { useState, useEffect, useCallback, useRef } from 'react'
import Dashboard from './components/Dashboard'
import LoginPage from './components/LoginPage'
import { TimezoneProvider } from './context/TimezoneContext'
import TimezoneSelector from './components/TimezoneSelector'
import AppShellV2 from './v2/AppShellV2'
import { isV2Enabled } from './v2/switch'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Position {
  symbol: string
  shares: number
  avg_cost: number
  current_price: number
  current_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  entry_confidence?: number
  bayes_confidence?: number
}

export interface Trade {
  id?: number
  symbol: string
  action: 'BUY' | 'SELL'
  shares: number
  price: number
  timestamp: string
  reasoning: string
  pnl: number
  agent_name?: string
  agent_id?: number
}

export interface Signal {
  action: 'BUY' | 'SELL' | 'HOLD'
  confidence: number
  reasoning: string
  timestamp: string
}

export interface Agent {
  id: number
  name: string
  strategy: string
  is_active: boolean
  cash: number
  total_value: number
  position_value: number
  total_return_pct: number
  total_return: number
  win_rate: number
  sharpe_ratio: number
  max_drawdown: number
  total_trades: number
  positions: Position[]
  recent_trades: Trade[]
  last_signals: Record<string, Signal>
  value_history: Array<{ timestamp: string; value: number }>
  avg_mae?: number
  avg_mfe?: number
  avg_captured_pct?: number
  rank?: number
}

export interface AppData {
  agents: Agent[]
  prices: Record<string, number>
  price_changes: Record<string, number>
  leaderboard: Agent[]
  is_running: boolean
  cycle_count: number
  timestamp: string
  watchlist: string[]
}

// ── WebSocket Hook ────────────────────────────────────────────────────────────

function useWebSocket(url: string, onMessage: (data: AppData) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectDelay = useRef(1000)
  const [connected, setConnected] = useState(false)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      reconnectDelay.current = 1000
      // Ping every 25 seconds
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping')
        }
      }, 25000)
      ws.addEventListener('close', () => clearInterval(pingInterval))
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'update') {
          onMessage(data)
        }
      } catch (e) {
        if (event.data !== 'pong') {
          console.warn('WebSocket: unexpected message format', event.data)
        }
      }
    }

    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null
      // Exponential backoff reconnect
      reconnectDelay.current = Math.min(reconnectDelay.current * 1.5, 30000)
      reconnectTimer.current = setTimeout(connect, reconnectDelay.current)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [url, onMessage])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  return connected
}

// ── Main App ──────────────────────────────────────────────────────────────────

// Always route WebSocket through Vite proxy — browser only needs to trust port 5173
const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`
const API_BASE = ''

export default function App() {
  // ── Authentication ──────────────────────────────────────────────────────────
  const [authChecked, setAuthChecked] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(false)

  useEffect(() => {
    fetch('/api/auth/check')
      .then(r => { if (r.ok) setIsAuthenticated(true) })
      .catch(() => {/* server unreachable — stay on login */})
      .finally(() => setAuthChecked(true))
  }, [])

  if (!authChecked) {
    // Brief loading state while checking session — avoids flash of login page
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading…</div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <LoginPage onLogin={() => setIsAuthenticated(true)} />
  }

  // ── Main App ────────────────────────────────────────────────────────────────
  return <AuthenticatedApp />
}

function AuthenticatedApp() {
  const [appData, setAppData] = useState<AppData>({
    agents: [],
    prices: {},
    price_changes: {},
    leaderboard: [],
    is_running: false,
    cycle_count: 0,
    timestamp: new Date().toISOString(),
    watchlist: [],
  })
  const [trades, setTrades] = useState<Trade[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [statusMessage, setStatusMessage] = useState('')
  const [forceTrading, setForceTrading] = useState(false)
  const [ollamaOnlyMode, setOllamaOnlyMode] = useState(true)  // default: always on
  const [ollamaOnlyExpiry, setOllamaOnlyExpiry] = useState<string | null>(null)

  const handleWsMessage = useCallback((data: AppData) => {
    setAppData(data)
  }, [])

  const wsConnected = useWebSocket(WS_URL, handleWsMessage)

  // Fetch initial data and trades
  useEffect(() => {
    fetchTrades()
    const interval = setInterval(fetchTrades, 15000)
    return () => clearInterval(interval)
  }, [])

  async function fetchTrades() {
    try {
      const res = await fetch(`${API_BASE}/api/trades?limit=100`)
      if (res.ok) {
        const data = await res.json()
        setTrades(data.trades || [])
      }
    } catch (e) {
      // silently fail
    }
  }

  async function handleStart() {
    setIsLoading(true)
    setStatusMessage('')
    try {
      const res = await fetch(`${API_BASE}/api/start`, { method: 'POST' })
      const data = await res.json()
      setStatusMessage(data.message)
      setAppData(prev => ({ ...prev, is_running: true }))
    } catch (e) {
      setStatusMessage('Failed to start: server unavailable')
    } finally {
      setIsLoading(false)
      setTimeout(() => setStatusMessage(''), 4000)
    }
  }

  async function handleStop() {
    setIsLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/stop`, { method: 'POST' })
      const data = await res.json()
      setStatusMessage(data.message)
      setAppData(prev => ({ ...prev, is_running: false }))
    } catch (e) {
      setStatusMessage('Failed to stop')
    } finally {
      setIsLoading(false)
      setTimeout(() => setStatusMessage(''), 3000)
    }
  }

  async function handleForceTrading() {
    const next = !forceTrading
    try {
      const res = await fetch(`${API_BASE}/api/force-trading?enabled=${next}`, { method: 'POST' })
      if (res.ok) {
        setForceTrading(next)
        setStatusMessage(next ? 'Force-trading ON — bypassing market hours' : 'Force-trading OFF')
        setTimeout(() => setStatusMessage(''), 4000)
      }
    } catch (e) {
      setStatusMessage('Failed to toggle force-trading')
      setTimeout(() => setStatusMessage(''), 3000)
    }
  }

  async function handleOllamaMode() {
    const next = !ollamaOnlyMode
    try {
      const res = await fetch(`${API_BASE}/api/ollama-mode?enabled=${next}&hours=24`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setOllamaOnlyMode(next)
        setOllamaOnlyExpiry(next ? data.expires_at : null)
        setStatusMessage(next ? 'Ollama-only mode ON (24h)' : 'Ollama-only mode OFF')
        setTimeout(() => setStatusMessage(''), 4000)
      }
    } catch (e) {
      setStatusMessage('Failed to toggle Ollama-only mode')
      setTimeout(() => setStatusMessage(''), 3000)
    }
  }

  async function handleReset() {
    if (!confirm('Reset all portfolios? This cannot be undone.')) return
    setIsLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/reset`, { method: 'POST' })
      const data = await res.json()
      setStatusMessage(data.message)
      setTrades([])
      setAppData(prev => {
        const resetAgents = prev.agents.map(a => ({
          ...a,
          cash: 100000,
          total_value: 100000,
          position_value: 0,
          total_return_pct: 0,
          total_return: 0,
          win_rate: 0,
          sharpe_ratio: 0,
          max_drawdown: 0,
          total_trades: 0,
          positions: [],
          recent_trades: [],
          last_signals: {},
          value_history: [],
        }))
        return {
          ...prev,
          is_running: false,
          cycle_count: 0,
          agents: resetAgents,
          leaderboard: resetAgents,
        }
      })
    } catch (e) {
      setStatusMessage('Failed to reset')
    } finally {
      setIsLoading(false)
      setTimeout(() => setStatusMessage(''), 3000)
    }
  }

  // v2 prototype: render the new shell behind ?v=2 (legacy UI is the default)
  if (isV2Enabled()) {
    return (
      <AppShellV2
        data={appData}
        trades={trades}
        wsConnected={wsConnected}
        ollamaOnly={ollamaOnlyMode}
      />
    )
  }

  return (
    <TimezoneProvider>
    <div className="min-h-screen bg-gray-900 text-gray-100">
      {/* Header */}
      <header className="gradient-border sticky top-0 z-50">
        <div className="max-w-screen-2xl mx-auto px-4 py-3 flex items-center justify-between">
          {/* Title */}
          <div className="flex items-center gap-3">
            <div className="text-2xl">🤖</div>
            <div>
              <h1 className="text-lg font-bold text-white leading-none">
                AI Trading Competition
              </h1>
              <p className="text-xs text-gray-400 mt-0.5">
                {appData.agents.length} agents competing • Cycle #{appData.cycle_count}
              </p>
            </div>
          </div>

          {/* Status & Controls */}
          <div className="flex items-center gap-3">
            {/* Connection status */}
            <div className={`flex items-center gap-1.5 text-xs ${wsConnected ? 'text-green-400' : 'text-gray-500'}`}>
              <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
              {wsConnected ? 'Live' : 'Connecting...'}
            </div>

            {/* Trading status */}
            <div className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-full border ${
              appData.is_running
                ? 'text-green-400 border-green-700/50 bg-green-900/20'
                : 'text-gray-400 border-gray-700 bg-gray-800/50'
            }`}>
              <div className={`w-1.5 h-1.5 rounded-full ${appData.is_running ? 'bg-green-400' : 'bg-gray-500'}`} />
              {appData.is_running ? 'Trading Active' : 'Paused'}
            </div>

            {/* Status message */}
            {statusMessage && (
              <span className="text-xs text-blue-400 animate-pulse">{statusMessage}</span>
            )}

            {/* Timezone selector */}
            <TimezoneSelector />

            {/* Force-trading toggle */}
            <button
              onClick={handleForceTrading}
              title="Bypass market hours gate for testing"
              className={`text-xs px-3 py-1.5 rounded border transition-colors ${
                forceTrading
                  ? 'bg-orange-700 border-orange-500 text-white hover:bg-orange-600'
                  : 'bg-gray-800 border-gray-600 text-gray-400 hover:text-gray-200 hover:border-gray-400'
              }`}
            >
              {forceTrading ? '⚡ Force ON' : '⚡ Force OFF'}
            </button>

            {/* Ollama-only mode toggle */}
            <button
              onClick={handleOllamaMode}
              title={ollamaOnlyMode ? 'Ollama is the primary model (click to temporarily enable Claude/OpenAI)' : 'Claude/OpenAI active — click to switch back to Ollama-only'}
              className={`text-xs px-3 py-1.5 rounded border transition-colors ${
                ollamaOnlyMode
                  ? 'bg-purple-700 border-purple-500 text-white hover:bg-purple-600'
                  : 'bg-gray-800 border-gray-600 text-gray-400 hover:text-gray-200 hover:border-gray-400'
              }`}
            >
              {ollamaOnlyMode ? '🦙 Local AI' : '☁ Cloud AI'}
            </button>

            {/* Control buttons */}
            <div className="flex gap-2">
              {!appData.is_running ? (
                <button
                  onClick={handleStart}
                  disabled={isLoading}
                  className="btn-success text-xs px-3 py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  ▶ Start
                </button>
              ) : (
                <button
                  onClick={handleStop}
                  disabled={isLoading}
                  className="btn-danger text-xs px-3 py-1.5 disabled:opacity-50"
                >
                  ⏸ Stop
                </button>
              )}
              <button
                onClick={handleReset}
                disabled={isLoading}
                className="btn-secondary text-xs px-3 py-1.5 disabled:opacity-50"
              >
                ↺ Reset
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-screen-2xl mx-auto px-4 py-4">
        <Dashboard
          agents={appData.agents}
          prices={appData.prices}
          priceChanges={appData.price_changes || {}}
          leaderboard={appData.leaderboard}
          trades={trades}
          watchlist={appData.watchlist}
          isRunning={appData.is_running}
        />
      </main>
    </div>
    </TimezoneProvider>
  )
}
