import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import TelemetryPanelV2 from '../TelemetryPanelV2'

const sampleTelemetry = {
  cpu_pct: 42.5,
  memory: {
    total_gb: 32,
    available_gb: 18,
    used_pct: 43.75,
  },
  process_memory_mb: 512,
  gpu: [
    {
      name: 'NVIDIA GeForce RTX 2060',
      util_pct: 65,
      vram_used_mb: 4096,
      vram_total_mb: 6144,
      temp_c: 72,
    },
  ],
  ollama: {
    online: true,
    mode: 'local',
    models: [
      {
        name: 'llama3.1:8b',
        size_gb: 4.7,
        processor: 'GPU',
        expires_at: '2026-04-21T16:00:00Z',
      },
    ],
  },
  scan_history: {
    durations_sec: [3.2, 4.1, 3.8, 5.0],
    avg_sec: 4.0,
    count: 4,
  },
}

describe('TelemetryPanelV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => sampleTelemetry,
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the system telemetry header', async () => {
    render(<TelemetryPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/SYSTEM TELEMETRY/i)).toBeInTheDocument()
    })
  })

  it('renders GPU and Ollama model details when data is returned', async () => {
    render(<TelemetryPanelV2 />)
    await waitFor(() => {
      expect(screen.getByText(/NVIDIA GeForce RTX 2060/i)).toBeInTheDocument()
    })
    expect(screen.getByText('llama3.1:8b')).toBeInTheDocument()
  })

  it('shows the loading state before data arrives', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    render(<TelemetryPanelV2 />)
    expect(screen.getByText(/LOADING TELEMETRY/i)).toBeInTheDocument()
  })
})
