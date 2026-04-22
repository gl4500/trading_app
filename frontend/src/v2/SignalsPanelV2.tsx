import React, { useEffect, useState } from 'react'

const API_BASE = ''

interface SourceDetail {
  score: number | null
  weight: number
  bull?: number
  hold?: number
  bear?: number
  total?: number
  price_target?: number | null
  surprise_pct?: number | null
  articles?: number
  congress_buys?: number
  congress_sells?: number
  congress_total?: number
  total_filings?: number
  window_days?: number
}

interface CompositeSignal {
  symbol: string
  composite_score: number
  confidence: number
  verdict: string
  sources: {
    analyst_consensus: SourceDetail
    earnings_surprise: SourceDetail
    alpaca_news: SourceDetail
    yahoo_news: SourceDetail
    congressional_trades: SourceDetail
  }
  yahoo_news_headlines: string[]
}

type SortCol = 'composite' | 'confidence' | 'analyst' | 'earnings' | 'alpaca' | 'yahoo' | 'congress'
type VerdictFilter = 'all' | 'bull' | 'neutral' | 'bear'

const PANEL: React.CSSProperties = {
  background: 'var(--bg-panel)',
  border: '1px solid var(--border-hair)',
  borderRadius: 'var(--radius-sm)',
  padding: '8px 10px',
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
  letterSpacing: '0.05em',
}

const TH: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  letterSpacing: '0.12em',
  color: 'var(--text-dim)',
  textTransform: 'uppercase',
  padding: '4px 6px',
  fontWeight: 500,
  borderBottom: '1px solid var(--border-hair)',
  textAlign: 'left',
  cursor: 'pointer',
  userSelect: 'none',
}

const TD: React.CSSProperties = {
  padding: '4px 6px',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontVariantNumeric: 'tabular-nums',
  color: 'var(--text-primary)',
}

function scoreColor(s: number | null): string {
  if (s === null) return 'var(--text-dim)'
  if (s >=  0.15) return 'var(--accent-green)'
  if (s <= -0.15) return 'var(--accent-red)'
  return 'var(--accent-amber)'
}

function fmt(n: number | null | undefined, decimals = 2, sign = false): string {
  if (n == null) return '—'
  const s = n.toFixed(decimals)
  return sign && n > 0 ? `+${s}` : s
}

function colScore(sig: CompositeSignal, col: SortCol): number {
  const s = sig.sources ?? ({} as CompositeSignal['sources'])
  switch (col) {
    case 'composite':  return sig.composite_score ?? 0
    case 'confidence': return sig.confidence ?? 0
    case 'analyst':    return s.analyst_consensus?.score   ?? -9
    case 'earnings':   return s.earnings_surprise?.score   ?? -9
    case 'alpaca':     return s.alpaca_news?.score         ?? -9
    case 'yahoo':      return s.yahoo_news?.score          ?? -9
    case 'congress':   return s.congressional_trades?.score ?? -9
  }
}

// Score bar — terminal-style hairline gauge with cyan/red/amber fill, centred at zero.
function ScoreBar({ score }: { score: number | null }) {
  if (score === null) return <span style={{ ...LABEL }}>—</span>
  const pct = Math.max(0, Math.min(100, ((score + 1) / 2) * 100))
  const fill = scoreColor(score)
  return (
    <div style={{
      position: 'relative',
      height: 4,
      background: 'var(--bg-input)',
      border: '1px solid var(--border-hair)',
      overflow: 'hidden',
    }}>
      {/* zero centre marker */}
      <div style={{
        position: 'absolute',
        left: '50%', top: 0, bottom: 0,
        width: 1,
        background: 'var(--border-soft)',
      }} />
      {score >= 0 ? (
        <div style={{
          position: 'absolute',
          left: '50%', top: 0, bottom: 0,
          width: `${pct - 50}%`,
          background: fill,
          opacity: 0.8,
        }} />
      ) : (
        <div style={{
          position: 'absolute',
          right: '50%', top: 0, bottom: 0,
          width: `${50 - pct}%`,
          background: fill,
          opacity: 0.8,
        }} />
      )}
    </div>
  )
}

function SortableTh({
  col, label, sub, current, dir, onSort, align,
}: {
  col: SortCol; label: string; sub?: string
  current: SortCol; dir: 'asc' | 'desc'
  onSort: (c: SortCol) => void
  align?: 'left' | 'center' | 'right'
}) {
  const active = current === col
  return (
    <th
      style={{ ...TH, textAlign: align ?? 'left', color: active ? 'var(--accent-cyan)' : 'var(--text-dim)' }}
      onClick={() => onSort(col)}
    >
      <span>{label}</span>
      {sub && <span style={{ color: 'var(--text-dim)', marginLeft: 4 }}>{sub}</span>}
      <span style={{ marginLeft: 4, color: active ? 'var(--accent-cyan)' : 'var(--border-soft)' }}>
        {active ? (dir === 'desc' ? '▼' : '▲') : '⇅'}
      </span>
    </th>
  )
}

function SignalRow({ sig }: { sig: CompositeSignal }) {
  const [expanded, setExpanded] = useState(false)
  const sources  = sig.sources ?? ({} as CompositeSignal['sources'])
  const analyst  = sources.analyst_consensus    ?? ({} as SourceDetail)
  const earnings = sources.earnings_surprise    ?? ({} as SourceDetail)
  const alpaca   = sources.alpaca_news          ?? ({} as SourceDetail)
  const yahoo    = sources.yahoo_news           ?? ({} as SourceDetail)
  const congress = sources.congressional_trades ?? ({} as SourceDetail)

  const score   = sig.composite_score ?? 0
  const confPct = Math.round((sig.confidence ?? 0) * 100)

  const verdictLabel = (sig.verdict ?? '').replace(/ \(.*\)$/, '')
  const verdictColor = score >= 0.15  ? 'var(--accent-green)'
                     : score <= -0.15 ? 'var(--accent-red)'
                                      : 'var(--accent-amber)'

  return (
    <>
      <tr style={{ borderTop: '1px solid var(--border-hair)' }}>
        {/* Symbol + verdict */}
        <td style={{ ...TD, whiteSpace: 'nowrap' }}>
          <div style={{ color: 'var(--accent-cyan)', fontWeight: 600, fontSize: 12 }}>{sig.symbol}</div>
          <div style={{
            ...LABEL,
            color: verdictColor,
            border: `1px solid ${verdictColor}`,
            display: 'inline-block',
            padding: '0 4px',
            marginTop: 2,
            fontSize: 9,
          }}>
            {verdictLabel || '—'}
          </div>
        </td>

        {/* Composite score */}
        <td style={{ ...TD, minWidth: 110 }}>
          <div style={{ color: scoreColor(score), fontWeight: 600 }}>
            {score >= 0 ? '+' : ''}{score.toFixed(2)}
          </div>
          <div style={{ marginTop: 3 }}>
            <ScoreBar score={score} />
          </div>
        </td>

        {/* Confidence */}
        <td style={{ ...TD, textAlign: 'center' }}>
          <span style={{
            color: confPct >= 70 ? 'var(--accent-green)' : confPct >= 40 ? 'var(--accent-amber)' : 'var(--accent-red)',
            fontWeight: 600,
          }}>{confPct}%</span>
        </td>

        {/* Analyst */}
        <td style={{ ...TD, minWidth: 110 }}>
          <div style={{ color: scoreColor(analyst.score ?? null), fontWeight: 600 }}>
            {fmt(analyst.score, 2, true)}
          </div>
          <div style={{ marginTop: 3 }}>
            <ScoreBar score={analyst.score ?? null} />
          </div>
          {(analyst.total ?? 0) > 0 && (
            <div style={{ ...LABEL, marginTop: 3, display: 'flex', gap: 4 }}>
              <span style={{ color: 'var(--accent-green)' }}>{analyst.bull}▲</span>
              <span style={{ color: 'var(--text-secondary)' }}>{analyst.hold}–</span>
              <span style={{ color: 'var(--accent-red)' }}>{analyst.bear}▼</span>
            </div>
          )}
          {analyst.price_target != null && (
            <div style={{ ...LABEL, marginTop: 2, color: 'var(--accent-cyan)' }}>
              PT ${analyst.price_target.toFixed(0)}
            </div>
          )}
        </td>

        {/* Earnings */}
        <td style={{ ...TD, minWidth: 90 }}>
          <div style={{ color: scoreColor(earnings.score ?? null), fontWeight: 600 }}>
            {fmt(earnings.score, 2, true)}
          </div>
          <div style={{ marginTop: 3 }}>
            <ScoreBar score={earnings.score ?? null} />
          </div>
          {earnings.surprise_pct != null && (
            <div style={{
              ...LABEL,
              marginTop: 2,
              color: earnings.surprise_pct >= 0 ? 'var(--accent-green)' : 'var(--accent-red)',
            }}>
              {earnings.surprise_pct >= 0 ? '+' : ''}{earnings.surprise_pct.toFixed(1)}% EPS
            </div>
          )}
        </td>

        {/* Alpaca */}
        <td style={{ ...TD }}>
          <div style={{ color: scoreColor(alpaca.score ?? null), fontWeight: 600 }}>
            {fmt(alpaca.score, 2, true)}
          </div>
          <div style={{ ...LABEL, marginTop: 2 }}>{alpaca.articles ?? 0} ART</div>
        </td>

        {/* Yahoo */}
        <td style={{ ...TD }}>
          <div style={{ color: scoreColor(yahoo.score ?? null), fontWeight: 600 }}>
            {fmt(yahoo.score, 2, true)}
          </div>
          <div style={{ ...LABEL, marginTop: 2 }}>{yahoo.articles ?? 0} ART</div>
        </td>

        {/* Congress */}
        <td style={{ ...TD, minWidth: 100 }}>
          {congress.score != null ? (
            <>
              <div style={{ color: scoreColor(congress.score), fontWeight: 600 }}>
                {fmt(congress.score, 2, true)}
              </div>
              <div style={{ ...LABEL, marginTop: 2, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {(congress.congress_buys ?? 0) > 0 && (
                  <span style={{ color: 'var(--accent-green)' }}>{congress.congress_buys}B</span>
                )}
                {(congress.congress_sells ?? 0) > 0 && (
                  <span style={{ color: 'var(--accent-red)' }}>{congress.congress_sells}S</span>
                )}
                {(congress.total_filings ?? 0) > 0 && (
                  <span style={{ color: 'var(--text-dim)' }}>{congress.total_filings}F4</span>
                )}
              </div>
            </>
          ) : (
            <div style={{ ...LABEL }}>
              {(congress.total_filings ?? 0) > 0 ? `${congress.total_filings} filings` : '—'}
            </div>
          )}
        </td>

        {/* Headlines toggle */}
        <td style={{ ...TD, textAlign: 'center' }}>
          {(sig.yahoo_news_headlines ?? []).length > 0 ? (
            <button
              type="button"
              onClick={() => setExpanded(e => !e)}
              style={{
                ...SELECT,
                cursor: 'pointer',
                color: 'var(--accent-cyan)',
              }}
            >
              {expanded ? '▲' : '▼'} {sig.yahoo_news_headlines.length}
            </button>
          ) : (
            <span style={{ ...LABEL }}>—</span>
          )}
        </td>
      </tr>

      {expanded && (
        <tr style={{ background: 'var(--bg-input)' }}>
          <td colSpan={9} style={{ padding: '6px 10px', borderTop: '1px solid var(--border-hair)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {(sig.yahoo_news_headlines ?? []).map((h, i) => (
                <div key={i} style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--text-secondary)',
                  borderLeft: '2px solid var(--border-soft)',
                  paddingLeft: 6,
                  lineHeight: 1.45,
                }}>
                  {h}
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default function SignalsPanelV2() {
  const [signals, setSignals]         = useState<Record<string, CompositeSignal>>({})
  const [loading, setLoading]         = useState(true)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [error, setError]             = useState<string | null>(null)
  const [sortCol, setSortCol]         = useState<SortCol>('composite')
  const [sortDir, setSortDir]         = useState<'desc' | 'asc'>('desc')
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>('all')
  const [symbolSearch, setSymbolSearch]   = useState('')

  const fetchSignals = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/signals`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSignals(data.signals ?? {})
      setLastUpdated(new Date().toLocaleTimeString())
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSignals()
    const interval = setInterval(fetchSignals, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  function handleSort(col: SortCol) {
    if (col === sortCol) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortCol(col); setSortDir('desc') }
  }

  const allSignals = Object.values(signals)
  const bullish = allSignals.filter(s => (s.composite_score ?? 0) >=  0.15).length
  const bearish = allSignals.filter(s => (s.composite_score ?? 0) <= -0.15).length
  const neutral = allSignals.length - bullish - bearish
  const avgScore = allSignals.length
    ? allSignals.reduce((s, x) => s + (x.composite_score ?? 0), 0) / allSignals.length
    : null

  const filtered = allSignals.filter(sig => {
    if (symbolSearch && !sig.symbol.includes(symbolSearch.toUpperCase())) return false
    const sc = sig.composite_score ?? 0
    if (verdictFilter === 'bull')    return sc >=  0.15
    if (verdictFilter === 'bear')    return sc <= -0.15
    if (verdictFilter === 'neutral') return sc > -0.15 && sc < 0.15
    return true
  })
  const sorted = [...filtered].sort((a, b) => {
    const diff = colScore(b, sortCol) - colScore(a, sortCol)
    return sortDir === 'desc' ? diff : -diff
  })

  const filterPill = (v: VerdictFilter, label: string, count: number, color: string) => {
    const active = verdictFilter === v
    return (
      <button
        type="button"
        onClick={() => setVerdictFilter(v)}
        style={{
          ...SELECT,
          color: active ? 'var(--bg-base)' : color,
          background: active ? color : 'var(--bg-input)',
          borderColor: color,
          cursor: 'pointer',
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
        }}
      >
        {label} {count}
      </button>
    )
  }

  return (
    <div style={PANEL}>
      <div style={HEADER}>
        <span>SIGNAL BOARD · {allSignals.length}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {avgScore !== null && (
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              fontVariantNumeric: 'tabular-nums',
              color: scoreColor(avgScore),
            }}>
              AVG {avgScore >= 0 ? '+' : ''}{avgScore.toFixed(2)}
            </span>
          )}
          {lastUpdated && (
            <span style={{ ...LABEL }}>{lastUpdated}</span>
          )}
          <button
            type="button"
            onClick={fetchSignals}
            style={{ ...SELECT, cursor: 'pointer', color: 'var(--accent-cyan)' }}
          >↻</button>
        </div>
      </div>

      {/* Weighting note */}
      <div style={{ ...LABEL, marginBottom: 6 }}>
        ANALYST 35% · EARNINGS 22% · ALPACA 18% · YAHOO 12% · CONGRESS 13%
      </div>

      {/* Filter pills */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ ...LABEL }}>FILTER</span>
        {filterPill('all', 'ALL', allSignals.length, 'var(--text-secondary)')}
        {filterPill('bull', '▲ BULL', bullish, 'var(--accent-green)')}
        {filterPill('neutral', '– NEU', neutral, 'var(--accent-amber)')}
        {filterPill('bear', '▼ BEAR', bearish, 'var(--accent-red)')}
        <input
          type="text"
          value={symbolSearch}
          onChange={e => setSymbolSearch(e.target.value)}
          placeholder="SYMBOL"
          aria-label="Symbol search"
          style={{
            ...SELECT,
            width: 90,
            marginLeft: 'auto',
            textTransform: 'uppercase',
          }}
        />
      </div>

      {loading ? (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--text-dim)', letterSpacing: '0.12em',
          border: '1px dashed var(--border-soft)',
        }}>
          LOADING SIGNALS…
        </div>
      ) : error ? (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--accent-red)', letterSpacing: '0.12em',
          border: '1px dashed var(--accent-red)',
        }}>
          FAILED TO LOAD SIGNALS — {error}
        </div>
      ) : sorted.length === 0 ? (
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--text-dim)', letterSpacing: '0.12em',
          border: '1px dashed var(--border-soft)',
        }}>
          {allSignals.length === 0
            ? 'NO SIGNAL DATA — START THE TRADING LOOP FIRST'
            : `NO ${verdictFilter.toUpperCase()} SIGNALS RIGHT NOW`}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={TH}>SYM</th>
                <SortableTh col="composite"  label="COMP"                 current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortableTh col="confidence" label="CONF"   align="center" current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortableTh col="analyst"    label="ANALYST" sub="35%"     current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortableTh col="earnings"   label="EARN"    sub="22%"     current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortableTh col="alpaca"     label="ALPACA"  sub="18%"     current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortableTh col="yahoo"      label="YAHOO"   sub="12%"     current={sortCol} dir={sortDir} onSort={handleSort} />
                <SortableTh col="congress"   label="CONG"    sub="13%"     current={sortCol} dir={sortDir} onSort={handleSort} />
                <th style={{ ...TH, textAlign: 'center', cursor: 'default' }}>HEAD</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(sig => <SignalRow key={sig.symbol} sig={sig} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
