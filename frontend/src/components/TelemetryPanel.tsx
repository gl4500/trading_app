import React, { useState, useEffect } from 'react'

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

function GaugeBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="w-full bg-gray-700 rounded-full h-2.5">
      <div
        className={`h-2.5 rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className="text-xl font-bold text-white">{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
    </div>
  )
}

export default function TelemetryPanel() {
  const [data, setData] = useState<TelemetryData | null>(null)
  const [error, setError] = useState('')
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  async function fetchTelemetry() {
    try {
      const res = await fetch('/api/telemetry')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setLastUpdated(new Date())
      setError('')
    } catch (e: any) {
      setError(e.message || 'Failed to fetch telemetry')
    }
  }

  useEffect(() => {
    fetchTelemetry()
    const interval = setInterval(fetchTelemetry, 5000)
    return () => clearInterval(interval)
  }, [])

  if (error) return (
    <div className="card p-4 text-red-400 text-sm">Telemetry error: {error}</div>
  )
  if (!data) return (
    <div className="card p-4 text-gray-400 text-sm">Loading telemetry...</div>
  )

  const cpuColor = data.cpu_pct > 80 ? 'bg-red-500' : data.cpu_pct > 50 ? 'bg-yellow-500' : 'bg-green-500'
  const memColor = data.memory.used_pct > 85 ? 'bg-red-500' : data.memory.used_pct > 65 ? 'bg-yellow-500' : 'bg-blue-500'

  function gpuUtilColor(pct: number) {
    return pct > 85 ? 'bg-red-500' : pct > 60 ? 'bg-yellow-500' : 'bg-green-500'
  }
  function gpuVramColor(pct: number) {
    return pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-yellow-500' : 'bg-violet-500'
  }
  function gpuTempColor(temp: number) {
    return temp > 85 ? 'text-red-400' : temp > 70 ? 'text-yellow-400' : 'text-green-400'
  }

  const durations = data.scan_history.durations_sec
  const maxDur = durations.length > 0 ? Math.max(...durations) : 1

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">System Telemetry</h2>
        <span className="text-xs text-gray-500">
          {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : ''} · auto-refresh 5s
        </span>
      </div>

      {/* System Resources */}
      <div className="card p-4 space-y-4">
        <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">System Resources</div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StatCard
            label="CPU Usage"
            value={`${data.cpu_pct.toFixed(1)}%`}
            sub="All cores"
          />
          <StatCard
            label="RAM Used"
            value={`${data.memory.used_pct.toFixed(1)}%`}
            sub={`${(data.memory.total_gb - data.memory.available_gb).toFixed(1)} GB / ${data.memory.total_gb} GB`}
          />
          <StatCard
            label="Backend Process"
            value={`${data.process_memory_mb.toFixed(0)} MB`}
            sub="Python RSS"
          />
        </div>

        <div className="space-y-3">
          <div>
            <div className="flex justify-between text-xs text-gray-400 mb-1">
              <span>CPU</span><span>{data.cpu_pct.toFixed(1)}%</span>
            </div>
            <GaugeBar pct={data.cpu_pct} color={cpuColor} />
          </div>
          <div>
            <div className="flex justify-between text-xs text-gray-400 mb-1">
              <span>Memory</span><span>{data.memory.used_pct.toFixed(1)}%</span>
            </div>
            <GaugeBar pct={data.memory.used_pct} color={memColor} />
          </div>
        </div>
      </div>

      {/* GPU Telemetry */}
      <div className="card p-4 space-y-3">
        <div className="flex items-center gap-3">
          <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">GPU</div>
          {data.gpu.length > 0 ? (
            <span className="text-xs px-2 py-0.5 rounded-full bg-green-900/50 text-green-400 border border-green-700 font-medium">
              {data.gpu.length} device{data.gpu.length > 1 ? 's' : ''} detected
            </span>
          ) : (
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-800 text-gray-500 border border-gray-700 font-medium">
              No NVIDIA GPU
            </span>
          )}
        </div>

        {data.gpu.length === 0 ? (
          <div className="text-sm text-gray-500 italic">
            No NVIDIA GPU detected — nvidia-smi not available or no discrete GPU present.
          </div>
        ) : (
          <div className="space-y-4">
            {data.gpu.map((gpu, idx) => {
              const vramPct = gpu.vram_total_mb > 0 ? (gpu.vram_used_mb / gpu.vram_total_mb) * 100 : 0
              return (
                <div key={idx} className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3">
                  {/* GPU name + index + temp */}
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-semibold text-white">{gpu.name}</div>
                      {data.gpu.length > 1 && (
                        <div className="text-xs text-gray-500">GPU {idx}</div>
                      )}
                    </div>
                    <div className={`text-lg font-bold ${gpuTempColor(gpu.temp_c)}`}>
                      {gpu.temp_c.toFixed(0)}°C
                    </div>
                  </div>

                  {/* Stat row */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="bg-gray-900/60 rounded-lg p-3 text-center">
                      <div className="text-xs text-gray-400 mb-1">Utilisation</div>
                      <div className="text-xl font-bold text-white">{gpu.util_pct.toFixed(0)}%</div>
                    </div>
                    <div className="bg-gray-900/60 rounded-lg p-3 text-center">
                      <div className="text-xs text-gray-400 mb-1">VRAM Used</div>
                      <div className="text-xl font-bold text-white">
                        {gpu.vram_used_mb >= 1024
                          ? `${(gpu.vram_used_mb / 1024).toFixed(1)} GB`
                          : `${gpu.vram_used_mb.toFixed(0)} MB`}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        of {gpu.vram_total_mb >= 1024
                          ? `${(gpu.vram_total_mb / 1024).toFixed(0)} GB`
                          : `${gpu.vram_total_mb.toFixed(0)} MB`}
                      </div>
                    </div>
                    <div className="bg-gray-900/60 rounded-lg p-3 text-center">
                      <div className="text-xs text-gray-400 mb-1">VRAM Free</div>
                      <div className="text-xl font-bold text-white">
                        {(() => {
                          const free = gpu.vram_total_mb - gpu.vram_used_mb
                          return free >= 1024
                            ? `${(free / 1024).toFixed(1)} GB`
                            : `${free.toFixed(0)} MB`
                        })()}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">{(100 - vramPct).toFixed(0)}% free</div>
                    </div>
                  </div>

                  {/* Gauge bars */}
                  <div className="space-y-2">
                    <div>
                      <div className="flex justify-between text-xs text-gray-400 mb-1">
                        <span>GPU Utilisation</span><span>{gpu.util_pct.toFixed(1)}%</span>
                      </div>
                      <GaugeBar pct={gpu.util_pct} color={gpuUtilColor(gpu.util_pct)} />
                    </div>
                    <div>
                      <div className="flex justify-between text-xs text-gray-400 mb-1">
                        <span>VRAM</span><span>{vramPct.toFixed(1)}%</span>
                      </div>
                      <GaugeBar pct={vramPct} color={gpuVramColor(vramPct)} />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Ollama Status */}
      <div className="card p-4 space-y-3">
        <div className="flex items-center gap-3">
          <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Ollama Local AI</div>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            data.ollama.online ? 'bg-green-900/50 text-green-400 border border-green-700' : 'bg-gray-800 text-gray-500 border border-gray-700'
          }`}>
            {data.ollama.online ? 'Online' : 'Offline'}
          </span>
          {data.ollama.mode === 'local' && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-purple-900/50 text-purple-400 border border-purple-700 font-medium">
              🦙 Primary Model
            </span>
          )}
        </div>

        {data.ollama.models.length === 0 ? (
          <div className="text-sm text-gray-500 italic">
            {data.ollama.online ? 'No models currently loaded (idle)' : 'Ollama server not reachable'}
          </div>
        ) : (
          <div className="space-y-2">
            {data.ollama.models.map(m => (
              <div key={m.name} className="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-3">
                <div>
                  <div className="text-sm font-medium text-white">{m.name}</div>
                  <div className="text-xs text-gray-400">{m.size_gb} GB loaded</div>
                </div>
                <div className="text-right">
                  <span className={`text-xs px-2 py-1 rounded font-medium ${
                    m.processor === 'GPU'
                      ? 'bg-green-900/50 text-green-400 border border-green-700'
                      : 'bg-blue-900/50 text-blue-400 border border-blue-700'
                  }`}>
                    {m.processor}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Scan History */}
      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Scanner Performance</div>
          {data.scan_history.count > 0 && (
            <div className="text-xs text-gray-400">
              avg <span className="text-white font-medium">{data.scan_history.avg_sec}s</span> · {data.scan_history.count} scans
            </div>
          )}
        </div>

        {durations.length === 0 ? (
          <div className="text-sm text-gray-500 italic">No scans completed yet this session.</div>
        ) : (
          <div className="space-y-1">
            <div className="text-xs text-gray-500 mb-2">Last {durations.length} scan durations (seconds)</div>
            <div className="flex items-end gap-1 h-16">
              {durations.map((d, i) => (
                <div
                  key={i}
                  className="flex-1 bg-purple-600 rounded-t min-h-[4px] transition-all"
                  style={{ height: `${Math.max((d / maxDur) * 100, 4)}%` }}
                  title={`${d}s`}
                />
              ))}
            </div>
            <div className="flex justify-between text-xs text-gray-600">
              <span>oldest</span>
              <span>latest</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
