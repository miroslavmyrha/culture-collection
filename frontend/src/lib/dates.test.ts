import { afterEach, describe, expect, it, vi } from 'vitest'
import { day, today } from './dates'

describe('dates (#67)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('writes a timestamp as its local day', () => {
    expect(day('2026-11-25T08:30:00')).toBe('2026-11-25')
  })

  it("gives today's local day", () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 10, 25, 23, 59))
    expect(today()).toBe('2026-11-25')
  })
})
