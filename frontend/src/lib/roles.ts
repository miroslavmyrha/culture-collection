import type { components } from '@/api/schema'

type Role = components['schemas']['Role']

/**
 * Curators and managers see and handle the lab's depositors, deposits and MTA templates
 * (deposits.view, deposits.manage). The one rule behind the deposits tab, its pages and its
 * buttons. The server decides; this only hides what it would refuse.
 */
export const canHandleDeposits = (role: Role | undefined): boolean => role === 'curator' || role === 'manager'
