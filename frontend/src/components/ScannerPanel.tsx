import React, { useEffect, useState } from 'react'
import { useTimezone } from '../context/TimezoneContext'
import { formatTime } from '../utils/time'

const API_BASE = ''  // always use Vite proxy — supports both HTTP and HTTPS

interface Candidate {
  symbol: string
  price: number
  pct_change: number
  vol_ratio: number
  momentum_score: number
}

interface Recommendation {
  symbol: string
  action: 'BUY' | 'SELL' | 'WATCH'
  confidence: number
  reasoning: string
  composite_score: number
  price_target?: number
  stop_loss_pct?: number
  catalysts?: string[]
  timestamp: string
}

interface ScanResult {
  status: string
  error?: string
  message?: string
  recommendations: Recommendation[]
  candidates: Candidate[]
  scanned_at?: string
  completed_at?: string
  cache_expires_in?: number
  is_stale?: boolean
  is_scanning?: boolean
}

// ── helpers ──────────────────────────────────────────────────────────────────

function actionColor(action: string) {
  if (action === 'BUY')   return 'text-emerald-400'
  if (action === 'SELL')  return 'text-red-400'
  return 'text-yellow-400'
}

function actionBg(action: string) {
  if (action === 'BUY')  return 'bg-emerald-900 border-emerald-700 text-emerald-300'
  if (action === 'SELL') return 'bg-red-900 border-red-700 text-red-300'
  return 'bg-yellow-900 border-yellow-700 text-yellow-300'
}

function scoreBg(s: number | null) {
  if (s === null) return 'bg-gray-700'
  if (s >= 0.4)  return 'bg-emerald-500'
  if (s >= 0.15) return 'bg-green-500'
  if (s <= -0.4) return 'bg-red-600'
  if (s <= -0.15) return 'bg-red-500'
  return 'bg-yellow-500'
}

function borderColor(action: string) {
  if (action === 'BUY')  return 'border-emerald-500'
  if (action === 'SELL') return 'border-red-500'
  return 'border-yellow-500'
}

function ConfBar({ pct }: { pct: number }) {
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 45 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400 font-mono w-8 text-right">{pct}%</span>
    </div>
  )
}

// ── RecommendationCard ────────────────────────────────────────────────────────

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const confPct = Math.round(rec.confidence * 100)
  const score   = rec.composite_score ?? 0

  return (
    <div className={`bg-gray-900 border border-gray-700 border-l-4 ${borderColor(rec.action)} rounded-xl p-4 space-y-3`}>

      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-white font-extrabold text-xl tracking-wide">{rec.symbol}</span>
          <span className={`text-xs px-2 py-0.5 rounded border font-bold ${actionBg(rec.action)}`}>
            {rec.action}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <div className={`w-3 h-3 rounded-full ${scoreBg(score)}`} />
          <span className="text-sm font-bold font-mono text-gray-300">
            {score >= 0 ? '+' : ''}{score.toFixed(2)}
          </span>
        </div>
      </div>

      {/* Confidence bar */}
      <div>
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>AI Confidence</span>
        </div>
        <ConfBar pct={confPct} />
      </div>

      {/* Reasoning */}
      <p className="text-sm text-gray-300 leading-relaxed">{rec.reasoning}</p>

      {/* Catalysts */}
      {rec.catalysts && rec.catalysts.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {rec.catalysts.map((c, i) => (
            <span key={i} className="text-xs px-2 py-0.5 bg-gray-800 text-gray-400 rounded-full border border-gray-700">
              {c}
            </span>
          ))}
        </div>
      )}

      {/* Price target / stop loss */}
      {(rec.price_target != null || rec.stop_loss_pct != null) && (
        <div className="flex gap-4 text-xs pt-1 border-t border-gray-800">
          {rec.price_target != null && (
            <div>
              <span className="text-gray-500">Target </span>
              <span className="text-blue-400 font-bold font-mono">${rec.price_target.toFixed(2)}</span>
            </div>
          )}
          {rec.stop_loss_pct != null && (
            <div>
              <span className="text-gray-500">Stop </span>
              <span className="text-red-400 font-bold font-mono">-{rec.stop_loss_pct}%</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── CandidateRow ──────────────────────────────────────────────────────────────

function CandidateRow({ c, rank }: { c: Candidate; rank: number }) {
  const up = c.pct_change >= 0
  return (
    <div className="flex items-center gap-3 py-1.5 border-b border-gray-800 last:border-0">
      <span className="text-xs text-gray-600 w-4 text-right">{rank}</span>
      <span className="text-sm font-bold text-white w-12">{c.symbol}</span>
      <span className="text-xs font-mono text-gray-400 flex-1">${c.price.toFixed(2)}</span>
      <span className={`text-xs font-bold font-mono ${up ? 'text-emerald-400' : 'text-red-400'}`}>
        {up ? '+' : ''}{c.pct_change.toFixed(2)}%
      </span>
      <span className="text-xs text-gray-600">vol×{c.vol_ratio.toFixed(1)}</span>
    </div>
  )
}

// ── ScannerPanel ──────────────────────────────────────────────────────────────

export default function ScannerPanel() {
  const { timeZone } = useTimezone()
  const [result, setResult]       = useState<ScanResult | null>(null)
  const [loading, setLoading]     = useState(false)
  const [scanning, setScanning]   = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [showAll, setShowAll]     = useState(false)

  const fetchCached = async (quiet = false) => {
    try {
      if (!quiet) setLoading(true)
      const res = await fetch(`${API_BASE}/api/scanner`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: ScanResult = await res.json()
      setResult(data)
      // Mirror backend in-progress flag into local scanning state
      setScanning(!!data.is_scanning)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      if (!quiet) setLoading(false)
    }
  }

  const runScan = async () => {
    try {
      setScanning(true)
      setError(null)
      const res = await fetch(`${API_BASE}/api/scanner/run`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: ScanResult = await res.json()
      setResult(data)
      setScanning(!!data.is_scanning)
    } catch (e: any) {
      setError(e.message)
      setScanning(false)
    }
  }

  // Poll every 3 s while a scan is in progress so navigating away and back still shows progress
  useEffect(() => {
    fetchCached()
  }, [])

  useEffect(() => {
    if (!scanning) return
    const id = setInterval(() => fetchCached(true), 3000)
    return () => clearInterval(id)
  }, [scanning])

  const recs = result?.recommendations ?? []
  const cands = result?.candidates ?? []
  const buys    = recs.filter(r => r.action === 'BUY').length
  const sells   = recs.filter(r => r.action === 'SELL').length
  const watches = recs.filter(r => r.action === 'WATCH').length

  const scannedTime = result?.scanned_at
    ? formatTime(result.scanned_at, timeZone)
    : null

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-white font-bold text-base flex items-center gap-2">
            <span className="text-purple-400">⟁</span> Agentic Stock Scanner
          </h2>
          <p className="text-xs text-gray-500">
            Claude autonomously scans ~160 stocks · finds high-conviction opportunities
          </p>
        </div>
        <div className="flex items-center gap-3">
          {recs.length > 0 && (
            <div className="flex gap-1.5 text-xs font-semibold">
              {buys    > 0 && <span className="px-2 py-1 bg-emerald-900 text-emerald-300 rounded-full">{buys} BUY</span>}
              {sells   > 0 && <span className="px-2 py-1 bg-red-900 text-red-300 rounded-full">{sells} SELL</span>}
              {watches > 0 && <span className="px-2 py-1 bg-yellow-900 text-yellow-300 rounded-full">{watches} WATCH</span>}
            </div>
          )}
          {scannedTime && (
            <span className="text-xs text-gray-600">Last scan: {scannedTime}</span>
          )}
          <button
            onClick={runScan}
            disabled={scanning}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-purple-700 hover:bg-purple-600 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg transition-colors font-semibold"
          >
            {scanning ? (
              <>
                <span className="animate-spin inline-block w-3 h-3 border border-white border-t-transparent rounded-full" />
                Scanning…
              </>
            ) : (
              '⟁ Run Scan'
            )}
          </button>
        </div>
      </div>

      {scanning && (
        <div className="bg-gray-900 border border-purple-800 rounded-xl p-6 text-center space-y-2">
          <div className="flex justify-center">
            <span className="animate-spin inline-block w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full" />
          </div>
          <p className="text-purple-300 font-semibold">Still thinking… AI agents are scanning the market</p>
          <p className="text-xs text-gray-500">
            Pre-screening ~160 stocks · deep-diving candidates · generating recommendations
          </p>
          <p className="text-xs text-gray-600">This takes 30–90 seconds — results will appear automatically</p>
        </div>
      )}

      {!scanning && result?.is_stale && (
        <div className="bg-yellow-900/20 border border-yellow-700/50 rounded-xl px-4 py-2 text-xs text-yellow-400 flex items-center gap-2">
          <span>⚠</span>
          <span>Showing cached results from a previous session — run a new scan to refresh.</span>
        </div>
      )}

      {error && !scanning && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {!scanning && (result?.status === 'no_scan' || result?.status === 'scanning') && (
        <div className="bg-gray-900 border border-gray-700 rounded-xl p-8 text-center space-y-3">
          <div className="text-4xl text-gray-600">⟁</div>
          <p className="text-gray-400 font-semibold">No scan results yet</p>
          <p className="text-sm text-gray-600">The scanner runs automatically every 30 min during market hours.</p>
          <p className="text-xs text-gray-700">Click "Run Scan" to trigger one immediately.</p>
        </div>
      )}

      {!scanning && recs.length > 0 && (
        <div>
          <h3 className="text-xs text-gray-500 uppercase tracking-wider mb-3 font-semibold">
            Recommendations ({recs.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {recs
              .sort((a, b) => b.confidence - a.confidence)
              .map(rec => <RecommendationCard key={rec.symbol} rec={rec} />)}
          </div>
        </div>
      )}

      {!scanning && recs.length === 0 && result?.status === 'ok' && (
        <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 text-center text-gray-500 text-sm">
          Claude found no high-conviction opportunities in this scan. Try again later.
        </div>
      )}

      {/* Pre-screen candidates (collapsible) */}
      {!scanning && cands.length > 0 && (
        <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
          <button
            onClick={() => setShowAll(s => !s)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-xs text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
          >
            <span className="font-semibold uppercase tracking-wider">
              Pre-screened Momentum Candidates ({cands.length})
            </span>
            <span>{showAll ? '▲' : '▼'}</span>
          </button>
          {showAll && (
            <div className="px-4 pb-3">
              {cands.map((c, i) => (
                <CandidateRow key={c.symbol} c={c} rank={i + 1} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
