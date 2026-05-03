import { describe, it, expect } from 'vitest'
import { isV2Enabled } from '../switch'

describe('isV2Enabled', () => {
  it('returns true when search contains v=2', () => {
    expect(isV2Enabled('?v=2')).toBe(true)
    expect(isV2Enabled('?foo=bar&v=2')).toBe(true)
  })
  it('returns false otherwise', () => {
    expect(isV2Enabled('')).toBe(false)
    expect(isV2Enabled('?v=1')).toBe(false)
    expect(isV2Enabled('?v=22')).toBe(false)
  })
})
