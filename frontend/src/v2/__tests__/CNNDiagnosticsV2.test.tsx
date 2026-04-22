import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import CNNDiagnosticsV2 from '../CNNDiagnosticsV2'

const populated = {
  trained: true,
  device: 'cuda',
  n_channels: 9,
  n_train: 1024,
  n_val: 256,
  final_train_mse: 0.0123,
  final_val_mse: 0.0234,
  overfit_ratio: 1.9,
  diagnosis: 'OK',
  walk_forward_efficiency: 0.85,
  wfe_status: 'HEALTHY',
  train_loss_curve: [0.5, 0.3, 0.2, 0.15, 0.12, 0.1, 0.09, 0.08],
  val_loss_curve:   [0.55, 0.35, 0.25, 0.2, 0.17, 0.15, 0.14, 0.13],
  learned_weights: { momentum: 0.34, sentiment: 0.21, technicals: 0.45 },
  weight_delta: 0.05,
  last_trained: '2026-04-21T08:00:00Z',
}

const untrained = {
  trained: false,
  device: 'cpu',
  n_channels: 0,
  n_train: 0,
  n_val: 0,
  final_train_mse: 0,
  final_val_mse: 0,
  overfit_ratio: 0,
  diagnosis: 'UNTRAINED',
  walk_forward_efficiency: 0,
  wfe_status: 'UNTRAINED',
  train_loss_curve: [],
  val_loss_curve: [],
  learned_weights: {},
  weight_delta: 0,
  last_trained: null,
}

describe('CNNDiagnosticsV2', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => populated,
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders untrained state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => untrained,
    }))
    render(<CNNDiagnosticsV2 />)
    await waitFor(() => {
      // both diagnosis & wfe are UNTRAINED — at least one match should exist
      expect(screen.getAllByText(/UNTRAINED/i).length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders diagnosis pill, WFE pill, and an SVG sparkline when populated', async () => {
    render(<CNNDiagnosticsV2 />)
    await waitFor(() => {
      expect(screen.getByText(/DIAGNOSIS/i)).toBeInTheDocument()
    })
    // Diagnosis pill text
    expect(screen.getAllByText(/\bOK\b/).length).toBeGreaterThanOrEqual(1)
    // WFE pill text
    expect(screen.getAllByText(/HEALTHY/i).length).toBeGreaterThanOrEqual(1)
    // Sparkline svg exists
    expect(document.querySelector('svg')).not.toBeNull()
  })

  it('refetches on refresh click', async () => {
    render(<CNNDiagnosticsV2 />)
    await waitFor(() => {
      expect(screen.getByText(/DIAGNOSIS/i)).toBeInTheDocument()
    })
    const fetchMock = (globalThis as any).fetch as ReturnType<typeof vi.fn>
    const before = fetchMock.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: /refresh/i }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(before)
    })
  })
})
