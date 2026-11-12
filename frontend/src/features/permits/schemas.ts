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

const text = (value: string | null | undefined) => value ?? ''

/** The line for a permit that is in force today: valid, or expiring soon. */
function inForceDetail(p: Permit): string {
  if (p.days_left === null) return 'No expiry stated'
  if (p.days_left === 0) return `Last valid day today, ${text(p.last_valid_day)}`
  return `Last valid day ${text(p.last_valid_day)}, in ${p.days_left} ${p.days_left === 1 ? 'day' : 'days'}`
}

const DETAILS: Partial<Record<Standing, (p: Permit) => string>> = {
  not_yet_valid: (p) => `Valid from ${p.valid_from}`,
  expired: (p) => `Last valid day ${text(p.expires_on)}`,
  ended: (p) => `Ended on ${text(p.ended_on)}: ${p.end_reason}`,
}

/** The line under the status: when it stops, or stopped, being valid. Dates are Czech days. */
export const standingDetail = (p: Permit): string => (DETAILS[p.standing] ?? inForceDetail)(p)
