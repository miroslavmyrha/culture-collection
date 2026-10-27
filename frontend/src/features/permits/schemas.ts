import type { components } from '@/api/schema'

export type Permit = components['schemas']['LabPermitOutput']
export type Standing = components['schemas']['StandingEnum']

/** Where a permit stands today, in words (biosafety.selectors.Standing on the server). */
export const STANDING_LABELS: Record<Standing, string> = {
  expires_soon: 'Expires soon',
  valid: 'Valid',
  not_yet_valid: 'Not valid yet',
  expired: 'Expired',
  ended: 'Ended',
}

/** The line under the status: when it stops, or stopped, being valid. Dates are Czech days. */
export function standingDetail(p: Permit): string {
  if (p.standing === 'not_yet_valid') return `Valid from ${p.valid_from}`
  if (p.standing === 'expired') return `Last valid day ${p.expires_on ?? ''}`
  if (p.standing === 'ended') return `Ended on ${p.ended_on ?? ''}: ${p.end_reason}`
  // Valid or expiring soon: in force today.
  if (p.days_left === null) return 'No expiry stated'
  if (p.days_left === 0) return `Last valid day today, ${p.last_valid_day ?? ''}`
  return `Last valid day ${p.last_valid_day ?? ''}, in ${p.days_left} ${p.days_left === 1 ? 'day' : 'days'}`
}
