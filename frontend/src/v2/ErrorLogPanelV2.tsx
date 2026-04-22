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

const PANEL: React.CSSProperties = {
  background: 'var(--bg-panel)',
  border: '1px solid var(--border-hair)',
  borderRadius: 'var(--radius-sm)',
  padding: '8px 10px',
  marginBottom: 8,
}

const HEADER: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 12,
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  letterSpacing: '0.15em',
  textTransform: 'uppercase',
  color: 'var(--accent-amber)',
  paddingBottom: 6,
  marginBottom: 8,
  borderBottom: '1px solid var(--border-hair)',
}

const LABEL: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--text-dim)',
}

const SELECT: React.CSSProperties = {
  background: 'var(--bg-input)',
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  color: 'var(--text-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  padding: '2px 6px',
}

function levelColor(lvl: string): string {
  if (lvl === 'CRITICAL') return 'var(--accent-red)'
  if (lvl === 'ERROR')    return 'var(--accent-red)'
  if (lvl === 'WARNING')  return 'var(--accent-amber)'
  return 'var(--text-dim)'
}

export default function ErrorLogPanelV2() {
  const [entries, setEntries] = useState<ErrorEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [offline, setOffline] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [showWarnings, setShowWarnings] = useState(false)

  const [analyzing, setAnalyzing] = useState(false)
  const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)

  const [levelFilter, setLevelFilter] = useState<string>('')

  const fetchEntries = useCallback(async () => {
    setLoading(true)
    setFetchError(null)
    setOffline(false)
    try {
      const errorsOnly = !showWarnings
      const resp = await fetch(`${API_BASE}/api/errors?limit=200&errors_only=${errorsOnly}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setEntries(data.entries || [])
    } catch (e: any) {
      if (e instanceof TypeError) setOffline(true)
      else setFetchError(e.message)
    } finally {
      setLoading(false)
    }
  }, [showWarnings])

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

  const errorCount   = entries.filter(e => e.level === 'ERROR' || e.level === 'CRITICAL').length
  const warningCount = entries.filter(e => e.level === 'WARNING').length

  return (
    <div>
      {/* Summary bar + filters */}
      <div style={PANEL}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
          <span style={LABEL}>{showWarnings ? 'ALL LOGS' : 'ERRORS ONLY'}</span>
          <span style={{ ...LABEL, color: 'var(--accent-red)' }}>
            {errorCount} ERR{errorCount !== 1 ? 'S' : ''}
          </span>
          <span style={{ ...LABEL, color: 'var(--accent-amber)' }}>
            {warningCount} WARN{warningCount !== 1 ? 'S' : ''}
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
            <button
              type="button"
              onClick={() => setShowWarnings(v => !v)}
              style={{
                ...SELECT,
                cursor: 'pointer',
                color: showWarnings ? 'var(--bg-base)' : 'var(--accent-amber)',
                background: showWarnings ? 'var(--accent-amber)' : 'var(--bg-input)',
                borderColor: 'var(--accent-amber)',
              }}
            >
              ⚠ WARN {showWarnings ? 'ON' : 'OFF'}
            </button>
            <select
              aria-label="Level filter"
              value={levelFilter}
              onChange={e => setLevelFilter(e.target.value)}
              style={SELECT}
            >
              <option value="">ALL LEVELS</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
              <option value="CRITICAL">CRITICAL</option>
            </select>
            <button
              type="button"
              onClick={fetchEntries}
              style={{ ...SELECT, cursor: 'pointer', color: 'var(--accent-cyan)' }}
            >
              {loading ? '…' : '⟳ REFRESH'}
            </button>
            <button
              type="button"
              onClick={handleAnalyze}
              disabled={analyzing || entries.length === 0}
              style={{
                ...SELECT,
                cursor: (analyzing || entries.length === 0) ? 'not-allowed' : 'pointer',
                color: (analyzing || entries.length === 0) ? 'var(--text-dim)' : 'var(--accent-violet)',
                borderColor: (analyzing || entries.length === 0) ? 'var(--border-hair)' : 'var(--accent-violet)',
              }}
            >
              {analyzing ? 'ANALYZING…' : 'ANALYZE WITH AI'}
            </button>
          </div>
        </div>
      </div>

      {/* AI Analysis panel */}
      {(analysis || analyzeError) && (
        <div style={PANEL}>
          <div style={HEADER}>
            <span>AI ANALYSIS</span>
          </div>
          {analyzeError && (
            <p style={{ margin: 0, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent-red)' }}>
              {analyzeError}
            </p>
          )}
          {analysis && (
            analysis.errors.length === 0 ? (
              <p style={{ margin: 0, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)' }}>
                {analysis.analysis}
              </p>
            ) : (
              <pre style={{
                margin: 0,
                whiteSpace: 'pre-wrap',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--text-primary)',
                lineHeight: 1.5,
                background: 'var(--bg-input)',
                padding: '6px 10px',
                border: '1px solid var(--border-hair)',
                overflowX: 'auto',
              }}>
                {analysis.analysis}
              </pre>
            )
          )}
        </div>
      )}

      {/* Error log */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>ERROR LOG · {filtered.length} ENTRIES</span>
        </div>

        {offline && (
          <div style={{
            border: '1px solid var(--accent-red)',
            background: 'var(--bg-input)',
            padding: '6px 10px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--accent-red)',
          }}>
            ⚠ BACKEND OFFLINE — START THE APP AND TRY AGAIN
          </div>
        )}

        {fetchError && !offline && (
          <div style={{
            border: '1px solid var(--accent-red)',
            background: 'var(--bg-input)',
            padding: '6px 10px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--accent-red)',
          }}>
            API ERROR: {fetchError}
          </div>
        )}

        {!offline && !fetchError && filtered.length === 0 && !loading && (
          <div style={{
            textAlign: 'center', padding: 18,
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--text-dim)', letterSpacing: '0.12em',
            border: '1px dashed var(--border-soft)',
          }}>
            NO LOG ENTRIES FOUND — ERRORS WILL APPEAR HERE
          </div>
        )}

        {!offline && filtered.length > 0 && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
            maxHeight: '60vh',
            overflowY: 'auto',
            paddingRight: 2,
          }}>
            {filtered.map((entry, i) => {
              const c = levelColor(entry.level)
              return (
                <div key={i} style={{
                  border: '1px solid var(--border-hair)',
                  borderLeft: `3px solid ${c}`,
                  background: entry.level === 'CRITICAL' ? 'rgba(239, 68, 68, 0.08)' : 'var(--bg-input)',
                  padding: '4px 8px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6, flexWrap: 'wrap' }}>
                    <span style={{
                      ...LABEL,
                      color: c,
                      border: `1px solid ${c}`,
                      padding: '0 4px',
                      flexShrink: 0,
                    }}>
                      {entry.level}
                    </span>
                    <span style={{ color: 'var(--text-dim)', flexShrink: 0 }}>{entry.timestamp}</span>
                    <span style={{ color: 'var(--accent-cyan)', flexShrink: 0 }}>[{entry.logger}]</span>
                    <span style={{ color: 'var(--text-primary)', wordBreak: 'break-all', flex: 1 }}>
                      {entry.message}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
