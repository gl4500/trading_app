import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SidebarV2, { TabId } from '../SidebarV2'

describe('SidebarV2', () => {
  it('renders 4 group headings', () => {
    render(<SidebarV2 active="chart" onSelect={() => {}} />)
    expect(screen.getByText('PERFORMANCE')).toBeInTheDocument()
    expect(screen.getByText('DECISIONS')).toBeInTheDocument()
    expect(screen.getByText('RISK & MODEL')).toBeInTheDocument()
    expect(screen.getByText('SYSTEM')).toBeInTheDocument()
  })

  it('marks the active item with aria-current=page', () => {
    render(<SidebarV2 active="signals" onSelect={() => {}} />)
    const signals = screen.getByRole('button', { name: /signals/i })
    expect(signals).toHaveAttribute('aria-current', 'page')
  })

  it('calls onSelect with the tab id when clicked', async () => {
    const onSelect = vi.fn()
    render(<SidebarV2 active="chart" onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('button', { name: /scanner/i }))
    expect(onSelect).toHaveBeenCalledWith<[TabId]>('scanner')
  })

  it('lists all 14 nav items', () => {
    render(<SidebarV2 active="chart" onSelect={() => {}} />)
    const expected = [
      'Chart', 'Agent Detail', 'Trades', 'Daily Roll-Up',
      'Signals', 'Scanner', 'Sentinel',
      'Regime', 'CNN Diagnostics', 'Drift', 'Tax',
      'Tokens', 'Errors', 'Telemetry',
    ]
    for (const label of expected) {
      expect(screen.getByRole('button', { name: new RegExp(label, 'i') })).toBeInTheDocument()
    }
  })
})
