import { describe, expect, it } from 'vitest'
import { canManageMembers, grantableRoles, ROLE_LABELS, ROLES } from './schemas'

describe('roles (invariants)', () => {
  it('has a label for every role and no other', () => {
    expect(Object.keys(ROLE_LABELS).toSorted()).toEqual(ROLES.toSorted())
  })

  it('never offers a role above the own one', () => {
    for (const own of ROLES) {
      for (const role of grantableRoles(own)) expect(ROLES.indexOf(role)).toBeLessThanOrEqual(ROLES.indexOf(own))
    }
  })

  it('lets only managers manage members, with every role', () => {
    expect(ROLES.filter(canManageMembers)).toEqual(['manager'])
    expect(ROLES.map((role) => grantableRoles(role).length)).toEqual([0, 0, 0, 4])
  })
})
