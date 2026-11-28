import { afterEach, describe, expect, it, vi } from 'vitest'
import { day, today } from './dates'

describe('dates (#67, #317)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('writes a timestamp as its Czech day', () => {
    expect(day('2026-11-25T08:30:00Z')).toBe('2026-11-25')
  })

  it('writes a winter timestamp after 23:00 UTC as the next Czech day', () => {
    expect(day('2026-11-27T23:41:51Z')).toBe('2026-11-28')
    expect(day('2026-11-27T22:59:59Z')).toBe('2026-11-27')
  })

  it('writes a summer timestamp after 22:00 UTC as the next Czech day', () => {
    expect(day('2026-06-30T22:00:00Z')).toBe('2026-07-01')
    expect(day('2026-06-30T21:59:59Z')).toBe('2026-06-30')
  })

  it("gives today's Czech day, not the machine's", () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-27T23:41:51Z'))
    expect(today()).toBe('2026-11-28')
  })
})
