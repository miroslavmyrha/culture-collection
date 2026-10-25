import { z } from 'zod'
import type { components } from '@/api/schema'
export type { PageParams } from '@/lib/paging'

export type Lab = components['schemas']['LabOutput']
export type Member = components['schemas']['MemberOutput']
export type Role = components['schemas']['Role']

/** Lowest first, as on the server (cultures/labs/permissions.py, ADR 0006). */
export const ROLES = ['viewer', 'technician', 'curator', 'manager'] as const satisfies readonly Role[]
export const ROLE_LABELS: Record<Role, string> = {
  viewer: 'Viewer',
  technician: 'Technician',
  curator: 'Curator',
  manager: 'Manager',
}

/** Only managers manage members. The server decides; this only hides what it would refuse. */
export const canManageMembers = (role: Role | undefined): boolean => role === 'manager'

/** The own role and every role below it: the ceiling of a grant (may_grant on the server). */
export const rolesUpTo = (own: Role): Role[] => ROLES.slice(0, ROLES.indexOf(own) + 1)

/** The roles a member manager may grant: up to their own, never above. */
export const grantableRoles = (own: Role): Role[] => (canManageMembers(own) ? rolesUpTo(own) : [])

export const roleOptions = (roles: readonly Role[]) => roles.map((value) => ({ value, label: ROLE_LABELS[value] }))

/** Add a member: an existing active user by username, with a role. Limits mirror the backend. */
export const addMemberSchema = z.object({
  username: z.string().trim().min(1, 'Enter a username').max(150, 'Use at most 150 characters'),
  role: z.enum(ROLES, 'Choose a role'),
})
export type AddMemberInput = z.output<typeof addMemberSchema>

export const changeRoleSchema = z.object({ role: z.enum(ROLES, 'Choose a role') })
export type ChangeRoleInput = z.output<typeof changeRoleSchema>

export type LocationGrant = components['schemas']['LocationGrantOutput']

/** A grant or a revocation of the regulated locations: always with a reason (ADR 0009). */
export const locationGrantSchema = z.object({ reason: z.string().trim().min(1, 'Say why').max(2000, 'Use at most 2000 characters') })
export type LocationGrantInput = z.input<typeof locationGrantSchema>
