import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'

describe('v2/theme.css', () => {
  const css = fs.readFileSync(path.resolve(__dirname, '../theme.css'), 'utf8')

  it('defines required color tokens scoped to data-ui=v2', () => {
    expect(css).toMatch(/:root\[data-ui="v2"\]/)
    expect(css).toContain('--bg-base:')
    expect(css).toContain('--accent-amber:')
    expect(css).toContain('--accent-cyan:')
    expect(css).toContain('--text-primary:')
    expect(css).toContain('--font-mono:')
  })

  it('uses near-black background (not pure black)', () => {
    expect(css).toMatch(/--bg-base:\s*#0a0a0a/)
  })
})
