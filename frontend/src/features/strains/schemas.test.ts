import { describe, expect, it } from 'vitest'
import { canManageStrains } from './schemas'

// #65: who manages strains, every role and none; a technician handles vials but not strains.
describe('canManageStrains', () => {
  it.each([
    ['viewer', false],
    ['technician', false],
    ['curator', true],
    ['manager', true],
    [undefined, false],
  ] as const)('a %s manages strains: %s', (role, expected) => {
    expect(canManageStrains(role)).toBe(expected)
  })
})
