import { describe, expect, it } from 'vitest'
import { getColumnCount, getItemHeight } from './useVirtualGrid'

describe('getColumnCount', () => {
  it('returns at least 1 for very narrow containers', () => {
    expect(getColumnCount(0, 50)).toBe(1)
    expect(getColumnCount(1, 50)).toBe(1)
    expect(getColumnCount(2, 50)).toBe(1)
  })

  it('zoom 0 (small thumbnails, 180px target) uses ~188px slots', () => {
    // 2 columns: floor((376 + 8) / (180 + 8)) = floor(384/188) = 2
    expect(getColumnCount(0, 376)).toBe(2)
    // 4 columns: floor((752 + 8) / (180 + 8)) = floor(760/188) = 4
    expect(getColumnCount(0, 752)).toBe(4)
  })

  it('zoom 1 (medium thumbnails, 240px target) uses ~248px slots', () => {
    // 2 columns: floor((488 + 8) / (240 + 8)) = floor(496/248) = 2
    expect(getColumnCount(1, 488)).toBe(2)
    // 3 columns: floor((736 + 8) / (240 + 8)) = floor(744/248) = 3
    expect(getColumnCount(1, 736)).toBe(3)
  })

  it('zoom 2 (large thumbnails, 320px target) uses ~328px slots', () => {
    // 2 columns: floor((648 + 8) / (320 + 8)) = floor(656/328) = 2
    expect(getColumnCount(2, 648)).toBe(2)
    // 1 column for small widths
    expect(getColumnCount(2, 300)).toBe(1)
  })

  it('scales up column count proportionally to container width', () => {
    const cols1 = getColumnCount(1, 500)
    const cols2 = getColumnCount(1, 1000)
    expect(cols2).toBeGreaterThan(cols1)
  })
})

describe('getItemHeight', () => {
  it('returns 180 for zoom level 0 (small)', () => {
    expect(getItemHeight(0)).toBe(180)
  })

  it('returns 240 for zoom level 1 (medium)', () => {
    expect(getItemHeight(1)).toBe(240)
  })

  it('returns 320 for zoom level 2 (large)', () => {
    expect(getItemHeight(2)).toBe(320)
  })
})
