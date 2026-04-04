import React, { useEffect, useState, useCallback } from 'react'

const API_BASE = ''

interface ErrorEntry {
  timestamp: string
  level: 'WARNING' | 'ERROR' | 'CRITICAL'
  logger: string
  message: string
}

interface AnalyzeResult {
  errors: string[]
  analysis: string
}

const LEVEL_STYLE: Record<string, string> = {
  WARNING:  'bg-yellow-900/40 text-yellow-300 border-yellow-700/40',
  ERROR:    'bg-red-900/40   text-red-300   border-red-700/40',
  CRITICAL: 'bg-red-800/60   text-red-200   border-red-600',
}

const LEVEL_BADGE: Record<string, string> = {
  WARNING:  'bg-yellow-800 text-yellow-200',
  ERROR:    'bg-red-800    text-red-200',
  CRITICAL: 'bg-red-600    text-white',
}

export default function ErrorLogPanel() {
  const [entries, setEntries] = useState<ErrorEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [offline, setOffline] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const [analyzing, setAnalyzing] = useState(false)
  const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)

  const [levelFilter, setLevelFilter] = useState<string>('')

  const fetchEntries = useCallback(async () => {
    setLoading(true)
    setFetchError(null)
    setOffline(false)
    try {
      const resp = await fetch(`${API_BASE}/api/errors?limit=200`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setEntries(data.entries || [])
    } catch (e: any) {
      if (e instanceof TypeError) setOffline(true)
      else setFetchError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchEntries()
    const id = setInterval(fetchEntries, 60_000)
    return () => clearInterval(id)
  }, [fetchEntries])

  async function handleAnalyze() {
    setAnalyzing(true)
    setAnalysis(null)
    setAnalyzeError(null)
    try {
      const resp = await fetch(`${API_BASE}/api/errors/analyze`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setAnalysis(data)
    } catch (e: any) {
      setAnalyzeError(e.message)
    } finally {
      setAnalyzing(false)
    }
  }

  const filtered = levelFilter
    ? entries.filter(e => e.level === levelFilter)
    : entries

  const errorCount    = entries.filter(e => e.level === 'ERROR' || e.level === 'CRITICAL').length
  const warningCount  = entries.filter(e => e.level === 'WARNING').length

  return (
    <div className="space-y-4">

      {/* Summary bar */}
      <div className="flex items-center gap-4 px-4 py-3 rounded-lg bg-gray-800/60 border border-gray-700/40 text-sm">
        <span className="text-gray-400">Last 200 log entries:</span>
        <span className="font-semibold text-red-400">{errorCount} error{errorCount !== 1 ? 's' : ''}</span>
        <span className="font-semibold text-yellow-400">{warningCount} warning{warningCount !== 1 ? 's' : ''}</span>
        <div className="ml-auto flex items-center gap-3">
          <select
            value={levelFilter}
            onChange={e => setLevelFilter(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs"
          >
            <option value="">All levels</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
            <option value="CRITICAL">CRITICAL</option>
          </select>
          <button
            onClick={fetchEntries}
            className="px-3 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-white transition-colors"
          >
            {loading ? '...' : '⟳ Refresh'}
          </button>
          <button
            onClick={handleAnalyze}
            disabled={analyzing || entries.length === 0}
            className="px-3 py-1 rounded text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white transition-colors"
          >
            {analyzing ? 'Analyzing...' : 'Analyze with AI'}
          </button>
        </div>
      </div>

      {/* AI Analysis panel */}
      {(analysis || analyzeError) && (
        <div className="card">
          <div className="card-header mb-3">AI Analysis</div>
          {analyzeError && (
            <p className="text-red-400 text-sm">{analyzeError}</p>
          )}
          {analysis && (
            <>
              {analysis.errors.length === 0 ? (
                <p className="text-gray-400 text-sm">{analysis.analysis}</p>
              ) : (
                <pre className="whitespace-pre-wrap text-sm text-gray-200 leading-relaxed font-mono bg-gray-900/60 rounded p-4 border border-gray-700/40 overflow-x-auto">
                  {analysis.analysis}
                </pre>
              )}
            </>
          )}
        </div>
      )}

      {/* Error log table */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <span className="card-header mb-0">Error Log</span>
          <span className="text-xs text-gray-500">{filtered.length} entries</span>
        </div>

        {offline && (
          <div className="flex items-center gap-2 px-3 py-2 rounded bg-red-900/40 border border-red-700 text-red-300 text-sm">
            <span>Backend offline — start the app and try again.</span>
          </div>
        )}

        {fetchError && !offline && (
          <div className="text-red-400 text-sm py-2">API error: {fetchError}</div>
        )}

        {!offline && !fetchError && filtered.length === 0 && !loading && (
          <p className="text-center text-gray-500 text-sm py-6">
            No log entries found. Errors and warnings will appear here when they occur.
          </p>
        )}

        {!offline && filtered.length > 0 && (
          <div className="space-y-1 max-h-[60vh] overflow-y-auto pr-1">
            {filtered.map((entry, i) => (
              <div
                key={i}
                className={`rounded px-3 py-2 border text-xs font-mono ${LEVEL_STYLE[entry.level] ?? 'bg-gray-800 text-gray-300 border-gray-700'}`}
              >
                <div className="flex items-start gap-2">
                  <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${LEVEL_BADGE[entry.level] ?? 'bg-gray-700 text-gray-200'}`}>
                    {entry.level}
                  </span>
                  <span className="text-gray-400 shrink-0">{entry.timestamp}</span>
                  <span className="text-gray-500 shrink-0">[{entry.logger}]</span>
                  <span className="break-all">{entry.message}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
