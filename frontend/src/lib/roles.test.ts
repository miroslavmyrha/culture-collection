import { describe, expect, it } from 'vitest'
import { canHandleDeposits, canManageMedia, canSeeReveals } from './roles'

describe('canHandleDeposits (invariant)', () => {
  it.each([
    ['viewer', false],
    ['technician', false],
    ['curator', true],
    ['manager', true],
    [undefined, false],
  ] as const)('%s: %s', (role, expected) => {
    expect(canHandleDeposits(role)).toBe(expected)
  })
})

describe('canManageMedia (invariant)', () => {
  it.each([
    ['viewer', false],
    ['technician', false],
    ['curator', true],
    ['manager', true],
    [undefined, false],
  ] as const)('%s: %s', (role, expected) => {
    expect(canManageMedia(role)).toBe(expected)
  })
})

describe('canSeeReveals (invariant)', () => {
  it.each([
    ['viewer', false],
    ['technician', false],
    ['curator', false],
    ['manager', true],
    [undefined, false],
  ] as const)('%s: %s', (role, expected) => {
    expect(canSeeReveals(role)).toBe(expected)
  })
})
