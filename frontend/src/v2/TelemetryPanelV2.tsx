import React, { useEffect, useState } from 'react'

const API_BASE = ''

interface OllamaModel {
  name: string
  size_gb: number
  processor: string
  expires_at: string
}

interface GpuDevice {
  name: string
  util_pct: number
  vram_used_mb: number
  vram_total_mb: number
  temp_c: number
}

interface TelemetryData {
  cpu_pct: number
  memory: {
    total_gb: number
    available_gb: number
    used_pct: number
  }
  process_memory_mb: number
  gpu: GpuDevice[]
  ollama: {
    online: boolean
    mode: string
    models: OllamaModel[]
  }
  scan_history: {
    durations_sec: number[]
    avg_sec: number
    count: number
  }
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

const NUM: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 16,
  color: 'var(--text-primary)',
  fontWeight: 600,
}

const TILE: React.CSSProperties = {
  background: 'var(--bg-input)',
  border: '1px solid var(--border-hair)',
  borderRadius: 'var(--radius-sm)',
  padding: '8px 10px',
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
}

const PILL: React.CSSProperties = {
  ...LABEL,
  border: '1px solid var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
  padding: '0 6px',
}

function gaugeColor(pct: number, hot = 80, warm = 50): string {
  if (pct > hot) return 'var(--accent-red)'
  if (pct > warm) return 'var(--accent-amber)'
  return 'var(--accent-green)'
}

function tempColor(temp: number): string {
  if (temp > 85) return 'var(--accent-red)'
  if (temp > 70) return 'var(--accent-amber)'
  return 'var(--accent-green)'
}

function GaugeBar({ pct, color }: { pct: number; color: string }) {
  const w = Math.max(0, Math.min(100, pct))
  return (
    <div style={{
      width: '100%',
      height: 4,
      background: 'var(--bg-input)',
      border: '1px solid var(--border-hair)',
      position: 'relative',
      overflow: 'hidden',
    }}>
      <div style={{
        width: `${w}%`,
        height: '100%',
        background: color,
        transition: 'width 400ms ease',
      }} />
    </div>
  )
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={TILE}>
      <span style={LABEL}>{label}</span>
      <span style={NUM}>{value}</span>
      {sub && <span style={{ ...LABEL, fontSize: 9 }}>{sub}</span>}
    </div>
  )
}

function fmtMb(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`
}

export default function TelemetryPanelV2() {
  const [data, setData] = useState<TelemetryData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchTelemetry() {
      try {
        const resp = await fetch(`${API_BASE}/api/telemetry`)
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const json = await resp.json()
        if (cancelled) return
        setData(json)
        setError(null)
        setOffline(false)
        setLastUpdated(new Date())
      } catch (e: any) {
        if (cancelled) return
        if (e instanceof TypeError) setOffline(true)
        else setError(e.message || 'Failed to fetch telemetry')
      }
    }

    fetchTelemetry()
    const id = setInterval(fetchTelemetry, 5000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  if (offline) {
    return (
      <div style={PANEL}>
        <div style={HEADER}><span>SYSTEM TELEMETRY</span></div>
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
      </div>
    )
  }

  if (error) {
    return (
      <div style={PANEL}>
        <div style={HEADER}><span>SYSTEM TELEMETRY</span></div>
        <div style={{
          border: '1px solid var(--accent-red)',
          background: 'var(--bg-input)',
          padding: '6px 10px',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--accent-red)',
        }}>
          API ERROR: {error}
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div style={PANEL}>
        <div style={HEADER}><span>SYSTEM TELEMETRY</span></div>
        <div style={{
          textAlign: 'center', padding: 18,
          fontFamily: 'var(--font-mono)', fontSize: 11,
          color: 'var(--text-dim)', letterSpacing: '0.12em',
          border: '1px dashed var(--border-soft)',
        }}>
          LOADING TELEMETRY…
        </div>
      </div>
    )
  }

  const cpuColor = gaugeColor(data.cpu_pct)
  const memColor = gaugeColor(data.memory.used_pct, 85, 65)
  const usedGb = (data.memory.total_gb - data.memory.available_gb).toFixed(1)
  const durations = data.scan_history.durations_sec
  const maxDur = durations.length > 0 ? Math.max(...durations) : 1

  return (
    <div>
      {/* Header */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>SYSTEM TELEMETRY</span>
          <span style={{ ...LABEL, color: 'var(--text-dim)' }}>
            {lastUpdated ? `UPDATED ${lastUpdated.toLocaleTimeString()}` : ''} · AUTO 5s
          </span>
        </div>

        {/* Stat tile row */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          gap: 8,
          marginBottom: 10,
        }}>
          <Tile label="CPU" value={`${data.cpu_pct.toFixed(1)}%`} sub="ALL CORES" />
          <Tile
            label="MEMORY"
            value={`${data.memory.used_pct.toFixed(1)}%`}
            sub={`${usedGb} / ${data.memory.total_gb} GB`}
          />
          <Tile
            label="BACKEND RSS"
            value={`${data.process_memory_mb.toFixed(0)} MB`}
            sub="PYTHON"
          />
        </div>

        {/* Gauges */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              fontFamily: 'var(--font-mono)', fontSize: 10,
              color: 'var(--text-dim)', marginBottom: 2,
              letterSpacing: '0.1em', textTransform: 'uppercase',
            }}>
              <span>CPU</span><span>{data.cpu_pct.toFixed(1)}%</span>
            </div>
            <GaugeBar pct={data.cpu_pct} color={cpuColor} />
          </div>
          <div>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              fontFamily: 'var(--font-mono)', fontSize: 10,
              color: 'var(--text-dim)', marginBottom: 2,
              letterSpacing: '0.1em', textTransform: 'uppercase',
            }}>
              <span>MEMORY</span><span>{data.memory.used_pct.toFixed(1)}%</span>
            </div>
            <GaugeBar pct={data.memory.used_pct} color={memColor} />
          </div>
        </div>
      </div>

      {/* GPU panel */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>GPU</span>
          <span style={{
            ...PILL,
            color: data.gpu.length > 0 ? 'var(--accent-green)' : 'var(--text-dim)',
            borderColor: data.gpu.length > 0 ? 'var(--accent-green)' : 'var(--border-soft)',
          }}>
            {data.gpu.length > 0
              ? `${data.gpu.length} DEVICE${data.gpu.length > 1 ? 'S' : ''}`
              : 'NO NVIDIA GPU'}
          </span>
        </div>

        {data.gpu.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: 14,
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--text-dim)', letterSpacing: '0.1em',
            border: '1px dashed var(--border-soft)',
          }}>
            NVIDIA-SMI UNAVAILABLE OR NO DISCRETE GPU
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.gpu.map((gpu, idx) => {
              const vramPct = gpu.vram_total_mb > 0
                ? (gpu.vram_used_mb / gpu.vram_total_mb) * 100
                : 0
              const free = gpu.vram_total_mb - gpu.vram_used_mb
              return (
                <div key={idx} style={{
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border-hair)',
                  padding: '8px 10px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 12,
                        color: 'var(--text-primary)',
                        fontWeight: 600,
                      }}>
                        {gpu.name}
                      </div>
                      {data.gpu.length > 1 && (
                        <div style={LABEL}>GPU {idx}</div>
                      )}
                    </div>
                    <div style={{
                      ...NUM,
                      color: tempColor(gpu.temp_c),
                    }}>
                      {gpu.temp_c.toFixed(0)}°C
                    </div>
                  </div>

                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                    gap: 6,
                  }}>
                    <Tile label="UTIL" value={`${gpu.util_pct.toFixed(0)}%`} />
                    <Tile
                      label="VRAM USED"
                      value={fmtMb(gpu.vram_used_mb)}
                      sub={`OF ${fmtMb(gpu.vram_total_mb)}`}
                    />
                    <Tile
                      label="VRAM FREE"
                      value={fmtMb(free)}
                      sub={`${(100 - vramPct).toFixed(0)}% FREE`}
                    />
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <div>
                      <div style={{
                        display: 'flex', justifyContent: 'space-between',
                        fontFamily: 'var(--font-mono)', fontSize: 10,
                        color: 'var(--text-dim)', marginBottom: 2,
                        letterSpacing: '0.1em', textTransform: 'uppercase',
                      }}>
                        <span>UTIL</span><span>{gpu.util_pct.toFixed(1)}%</span>
                      </div>
                      <GaugeBar pct={gpu.util_pct} color={gaugeColor(gpu.util_pct, 85, 60)} />
                    </div>
                    <div>
                      <div style={{
                        display: 'flex', justifyContent: 'space-between',
                        fontFamily: 'var(--font-mono)', fontSize: 10,
                        color: 'var(--text-dim)', marginBottom: 2,
                        letterSpacing: '0.1em', textTransform: 'uppercase',
                      }}>
                        <span>VRAM</span><span>{vramPct.toFixed(1)}%</span>
                      </div>
                      <GaugeBar pct={vramPct} color={gaugeColor(vramPct, 90, 70)} />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Ollama panel */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>OLLAMA LOCAL AI</span>
          <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <span style={{
              ...PILL,
              color: data.ollama.online ? 'var(--accent-green)' : 'var(--text-dim)',
              borderColor: data.ollama.online ? 'var(--accent-green)' : 'var(--border-soft)',
            }}>
              {data.ollama.online ? 'ONLINE' : 'OFFLINE'}
            </span>
            {data.ollama.mode === 'local' && (
              <span style={{
                ...PILL,
                color: 'var(--accent-violet)',
                borderColor: 'var(--accent-violet)',
              }}>
                PRIMARY
              </span>
            )}
          </span>
        </div>

        {data.ollama.models.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: 14,
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--text-dim)', letterSpacing: '0.1em',
            border: '1px dashed var(--border-soft)',
          }}>
            {data.ollama.online
              ? 'NO MODELS LOADED (IDLE)'
              : 'OLLAMA SERVER NOT REACHABLE'}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {data.ollama.models.map(m => (
              <div key={m.name} style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                background: 'var(--bg-input)',
                border: '1px solid var(--border-hair)',
                padding: '6px 10px',
              }}>
                <div>
                  <div style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 12,
                    color: 'var(--text-primary)',
                  }}>
                    {m.name}
                  </div>
                  <div style={LABEL}>{m.size_gb} GB LOADED</div>
                </div>
                <span style={{
                  ...PILL,
                  color: m.processor === 'GPU' ? 'var(--accent-green)' : 'var(--accent-cyan)',
                  borderColor: m.processor === 'GPU' ? 'var(--accent-green)' : 'var(--accent-cyan)',
                }}>
                  {m.processor}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Scanner performance */}
      <div style={PANEL}>
        <div style={HEADER}>
          <span>SCANNER PERFORMANCE</span>
          {data.scan_history.count > 0 && (
            <span style={{ ...LABEL, color: 'var(--text-dim)' }}>
              AVG <span style={{ color: 'var(--text-primary)' }}>{data.scan_history.avg_sec}s</span>
              {' · '}{data.scan_history.count} SCANS
            </span>
          )}
        </div>

        {durations.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: 14,
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: 'var(--text-dim)', letterSpacing: '0.1em',
            border: '1px dashed var(--border-soft)',
          }}>
            NO SCANS COMPLETED THIS SESSION
          </div>
        ) : (
          <div>
            <div style={{ ...LABEL, marginBottom: 6 }}>
              LAST {durations.length} SCAN DURATIONS (SECONDS)
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'flex-end',
              gap: 2,
              height: 60,
              padding: '4px 0',
              borderBottom: '1px solid var(--border-hair)',
            }}>
              {durations.map((d, i) => (
                <div
                  key={i}
                  title={`${d}s`}
                  style={{
                    flex: 1,
                    minHeight: 2,
                    height: `${Math.max((d / maxDur) * 100, 4)}%`,
                    background: 'var(--accent-violet)',
                  }}
                />
              ))}
            </div>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--text-dim)',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              marginTop: 4,
            }}>
              <span>OLDEST</span>
              <span>LATEST</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
