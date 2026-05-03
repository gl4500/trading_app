import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import CommandStripV2 from '../CommandStripV2'

const baseProps = {
  wsConnected: true,
  isRunning: true,
  ollamaOnly: true,
  haltedAgentCount: 0,
  driftWarningCount: 0,
  realizedPnlToday: 0,
  cycleCount: 42,
}

describe('CommandStripV2', () => {
  it('shows LIVE when ws connected', () => {
    render(<CommandStripV2 {...baseProps} />)
    expect(screen.getByText(/LIVE/)).toBeInTheDocument()
  })

  it('shows OFFLINE when ws disconnected', () => {
    render(<CommandStripV2 {...baseProps} wsConnected={false} />)
    expect(screen.getByText(/OFFLINE/)).toBeInTheDocument()
  })

  it('shows TRADING when running, PAUSED otherwise', () => {
    const { rerender } = render(<CommandStripV2 {...baseProps} isRunning={true} />)
    expect(screen.getByText(/TRADING/)).toBeInTheDocument()
    rerender(<CommandStripV2 {...baseProps} isRunning={false} />)
    expect(screen.getByText(/PAUSED/)).toBeInTheDocument()
  })

  it('shows local-AI label when ollamaOnly true, cloud-AI otherwise', () => {
    const { rerender } = render(<CommandStripV2 {...baseProps} ollamaOnly={true} />)
    expect(screen.getByText(/LOCAL/)).toBeInTheDocument()
    rerender(<CommandStripV2 {...baseProps} ollamaOnly={false} />)
    expect(screen.getByText(/CLOUD/)).toBeInTheDocument()
  })

  it('shows realized P&L with + sign and green class for positive', () => {
    render(<CommandStripV2 {...baseProps} realizedPnlToday={1234.5} />)
    const pnl = screen.getByTestId('pnl-today')
    expect(pnl.textContent).toMatch(/\+\$1,234\.50/)
  })

  it('shows realized P&L with - sign for negative', () => {
    render(<CommandStripV2 {...baseProps} realizedPnlToday={-789} />)
    const pnl = screen.getByTestId('pnl-today')
    expect(pnl.textContent).toMatch(/-\$789\.00/)
  })

  it('hides halted alert when count is 0, shows when >0', () => {
    const { rerender } = render(<CommandStripV2 {...baseProps} haltedAgentCount={0} />)
    expect(screen.queryByText(/HALTED/)).not.toBeInTheDocument()
    rerender(<CommandStripV2 {...baseProps} haltedAgentCount={2} />)
    expect(screen.getByText(/2 HALTED/)).toBeInTheDocument()
  })

  it('shows cycle count', () => {
    render(<CommandStripV2 {...baseProps} cycleCount={123} />)
    expect(screen.getByText(/CYCLE 123/)).toBeInTheDocument()
  })
})
