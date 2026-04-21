import React from 'react'
import {
  IconChart, IconAgent, IconTrades, IconRollup,
  IconSignals, IconScanner, IconSentinel,
  IconRegime, IconCNN, IconDrift, IconTax,
  IconTokens, IconErrors, IconTelemetry,
} from './icons'

export type TabId =
  | 'chart' | 'detail' | 'trades' | 'rollup'
  | 'signals' | 'scanner' | 'sentinel'
  | 'regime' | 'cnn' | 'drift' | 'tax'
  | 'tokens' | 'errors' | 'telemetry'

interface NavItem { id: TabId; label: string; Icon: React.FC<React.SVGProps<SVGSVGElement>> }
interface NavGroup { heading: string; items: NavItem[] }

const GROUPS: NavGroup[] = [
  { heading: 'PERFORMANCE', items: [
    { id: 'chart',  label: 'Chart',         Icon: IconChart },
    { id: 'detail', label: 'Agent Detail',  Icon: IconAgent },
    { id: 'trades', label: 'Trades',        Icon: IconTrades },
    { id: 'rollup', label: 'Daily Roll-Up', Icon: IconRollup },
  ]},
  { heading: 'DECISIONS', items: [
    { id: 'signals',  label: 'Signals',  Icon: IconSignals },
    { id: 'scanner',  label: 'Scanner',  Icon: IconScanner },
    { id: 'sentinel', label: 'Sentinel', Icon: IconSentinel },
  ]},
  { heading: 'RISK & MODEL', items: [
    { id: 'regime', label: 'Regime',          Icon: IconRegime },
    { id: 'cnn',    label: 'CNN Diagnostics', Icon: IconCNN },
    { id: 'drift',  label: 'Drift',           Icon: IconDrift },
    { id: 'tax',    label: 'Tax',             Icon: IconTax },
  ]},
  { heading: 'SYSTEM', items: [
    { id: 'tokens',    label: 'Tokens',    Icon: IconTokens },
    { id: 'errors',    label: 'Errors',    Icon: IconErrors },
    { id: 'telemetry', label: 'Telemetry', Icon: IconTelemetry },
  ]},
]

interface Props { active: TabId; onSelect: (id: TabId) => void }

export default function SidebarV2({ active, onSelect }: Props) {
  return (
    <nav
      aria-label="Primary"
      style={{
        background: 'var(--bg-panel)',
        borderRight: '1px solid var(--border-hair)',
        width: 200,
        height: '100vh',
        position: 'sticky',
        top: 0,
        overflowY: 'auto',
        padding: '12px 0',
        fontFamily: 'var(--font-display)',
      }}
    >
      <div style={{
        padding: '0 14px 14px',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        letterSpacing: '0.15em',
        color: 'var(--accent-amber)',
        borderBottom: '1px solid var(--border-hair)',
      }}>
        AI · TRADE · DESK
      </div>
      {GROUPS.map(group => (
        <div key={group.heading} style={{ marginTop: 16 }}>
          <div style={{
            padding: '0 14px 6px',
            fontSize: 10,
            letterSpacing: '0.18em',
            color: 'var(--text-dim)',
            fontFamily: 'var(--font-mono)',
          }}>
            {group.heading}
          </div>
          {group.items.map(({ id, label, Icon }) => {
            const isActive = id === active
            return (
              <button
                key={id}
                onClick={() => onSelect(id)}
                aria-current={isActive ? 'page' : undefined}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  width: '100%',
                  padding: '6px 14px',
                  background: isActive ? 'var(--bg-panel-hi)' : 'transparent',
                  borderTop: 'none',
                  borderRight: 'none',
                  borderBottom: 'none',
                  borderLeft: `2px solid ${isActive ? 'var(--accent-amber)' : 'transparent'}`,
                  color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontSize: 13,
                  fontFamily: 'var(--font-display)',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <Icon style={{ color: isActive ? 'var(--accent-amber)' : 'var(--text-dim)' }} />
                {label}
              </button>
            )
          })}
        </div>
      ))}
    </nav>
  )
}
