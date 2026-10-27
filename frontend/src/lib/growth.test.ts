import { describe, expect, it } from 'vitest'
import { makeMedium, mediumBrief, noGrowth } from '@/test/factories'
import { growthBody, growthDefaults, growthSchema, growthText, mediumChoices, temperatureText } from './growth'

const form = (over: Partial<ReturnType<typeof growthDefaults>> = {}) => ({ medium: '', temperature_low_c: '', temperature_high_c: '', atmosphere: '' as const, ...over })
const messages = (value: ReturnType<typeof form>) => {
  const result = growthSchema.safeParse(value)
  return result.success ? {} : Object.fromEntries(result.error.issues.map((i) => [String(i.path[0]), i.message]))
}

describe('temperatureText and growthText', () => {
  it('writes one degree, a range, and nothing', () => {
    expect(temperatureText({ temperature_low_c: 28, temperature_high_c: 28 })).toBe('28 °C')
    expect(temperatureText({ temperature_low_c: 28, temperature_high_c: null })).toBe('28 °C')
    expect(temperatureText({ temperature_low_c: 25, temperature_high_c: 30 })).toBe('25 to 30 °C')
    expect(temperatureText({ temperature_low_c: null, temperature_high_c: null })).toBe('')
  })

  it('joins what is recorded and marks a retired medium', () => {
    const lb = makeMedium({ name: 'LB' })
    expect(growthText(noGrowth())).toBe('Not recorded')
    expect(growthText({ medium: mediumBrief(lb), temperature_low_c: 37, temperature_high_c: 37, atmosphere: 'anaerobic' })).toBe('LB, 37 °C, Anaerobic')
    expect(growthText({ ...noGrowth(), medium: mediumBrief({ ...lb, retired_at: '2026-10-01T00:00:00Z' }) })).toBe('LB (retired)')
  })
})

describe('the growth form', () => {
  it('accepts empty fields, one degree and a range', () => {
    expect(messages(form())).toEqual({})
    expect(messages(form({ temperature_low_c: '28' }))).toEqual({})
    expect(messages(form({ temperature_low_c: '25', temperature_high_c: '30', atmosphere: 'aerobic' }))).toEqual({})
    expect(messages(form({ temperature_low_c: '0' }))).toEqual({})
    expect(messages(form({ temperature_low_c: '125' }))).toEqual({})
  })

  it.each([
    ['a fraction', form({ temperature_low_c: '28.5' }), 'temperature_low_c', 'Use whole degrees from 0 to 125 °C'],
    ['a negative', form({ temperature_low_c: '-1' }), 'temperature_low_c', 'Use whole degrees from 0 to 125 °C'],
    ['above the limit', form({ temperature_low_c: '126' }), 'temperature_low_c', 'Use whole degrees from 0 to 125 °C'],
    ['a bad high end', form({ temperature_low_c: '20', temperature_high_c: 'x' }), 'temperature_high_c', 'Use whole degrees from 0 to 125 °C'],
    ['a high end alone', form({ temperature_high_c: '30' }), 'temperature_low_c', 'Enter the low end too'],
    ['a high end below the low', form({ temperature_low_c: '30', temperature_high_c: '25' }), 'temperature_high_c', 'The high end is below the low end'],
  ])('refuses %s on its field', (_, value, field, message) => {
    expect(messages(value)[field]).toBe(message)
  })

  it('sends empty as none, a single value alone, and the medium by id', () => {
    expect(growthBody(form())).toEqual({ medium: null, temperature_low_c: null, temperature_high_c: null, atmosphere: '' })
    expect(growthBody(form({ medium: 'm1', temperature_low_c: '28', atmosphere: 'aerobic' }))).toEqual({ medium: 'm1', temperature_low_c: 28, temperature_high_c: null, atmosphere: 'aerobic' })
  })

  it('starts from the recorded values, a one-degree range as one box', () => {
    const lb = makeMedium()
    expect(growthDefaults({ medium: mediumBrief(lb), temperature_low_c: 28, temperature_high_c: 28, atmosphere: 'aerobic' })).toEqual(form({ medium: lb.public_id, temperature_low_c: '28', atmosphere: 'aerobic' }))
    expect(growthDefaults({ ...noGrowth(), temperature_low_c: 25, temperature_high_c: 30 })).toMatchObject({ temperature_low_c: '25', temperature_high_c: '30' })
  })
})

describe('mediumChoices', () => {
  it('offers the active media and the retired one the thing already has', () => {
    const active = makeMedium({ name: 'A' })
    const old = makeMedium({ name: 'B', retired_at: '2026-10-01T00:00:00Z' })
    const other = makeMedium({ name: 'C', retired_at: '2026-10-01T00:00:00Z' })
    expect(mediumChoices([active, old, other], null).map((m) => m.name)).toEqual(['A'])
    expect(mediumChoices([active, old, other], mediumBrief(old)).map((m) => m.name)).toEqual(['A', 'B'])
  })
})
