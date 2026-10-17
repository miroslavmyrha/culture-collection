import { describe, expect, it } from 'vitest'
import { canManageMembers, grantableRoles, ROLE_LABELS, ROLES, rolesUpTo } from './schemas'

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

  // Today only managers grant, and nothing is above them, so grantableRoles alone cannot show
  // the ceiling. The helper is tested for every role, as the server's may_grant is.
  it.each([
    ['viewer', ['viewer']],
    ['technician', ['viewer', 'technician']],
    ['curator', ['viewer', 'technician', 'curator']],
    ['manager', ['viewer', 'technician', 'curator', 'manager']],
  ] as const)('caps the roles of a %s at their own', (own, roles) => {
    expect(rolesUpTo(own)).toEqual(roles)
  })
})
