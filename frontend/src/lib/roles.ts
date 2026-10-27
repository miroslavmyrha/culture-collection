import type { components } from '@/api/schema'

type Role = components['schemas']['Role']

/**
 * Curators and managers see and handle the lab's depositors, deposits and MTA templates
 * (deposits.view, deposits.manage). The one rule behind the deposits tab, its pages and its
 * buttons. The server decides; this only hides what it would refuse.
 */
export const canHandleDeposits = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'

/**
 * Managers read the lab's permits (biosafety.view_permits, #82): they answer to the authority
 * for them. Staff record and end them in the Django admin. The server decides; this only hides
 * what it would refuse.
 */
export const canSeePermits = (role: Role | undefined): boolean => role === 'manager'

/**
 * Curators and managers add, edit and retire the lab's media (growth.manage_media, #79). Everyone
 * who sees the strains reads the media, to see what a strain is grown on. The server decides;
 * this only hides what it would refuse.
 */
export const canManageMedia = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'

/**
 * Managers read who revealed where the lab's regulated vials are (vials.view_reveals, #83): they
 * grant and revoke the location grant, so they read what the holders did with it. Holding the
 * grant gives no access to this log. The server decides; this only hides what it would refuse.
 */
export const canSeeReveals = (role: Role | undefined): boolean => role === 'manager'
