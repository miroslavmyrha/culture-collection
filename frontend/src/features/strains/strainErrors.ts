import { errorMessage, isApiError, readProblem } from '@/lib/api'

/** The permit a kind needs (ADR 0009), for the refusal the server sends. */
export const PERMIT_REFUSED = 'This lab holds no valid permit for this restriction. Staff record permits; until then the strain cannot be added with it.'
export const PERMIT_REFUSED_BY_KIND: Record<string, string> = {
  cz_vrat: 'This lab holds no valid SÚJB permit for highly risky agents (VRAT). Staff record the permit; until then the strain cannot be added with this restriction.',
  quarantine_pest:
    'This lab holds no valid ÚKZÚZ permit for quarantine pests. Staff record the permit; until then the strain cannot be added with this restriction.',
}
export const RISK_GROUP_4_REFUSED = 'The collection does not hold risk group 4 agents.'
/** Names no box: where a regulated strain is stays masked (ADR 0009). */
export const RISK_GROUP_ABOVE_BOX_CAP = "A box holding this strain's vials does not allow this risk group. Move the vials first."

/** The message a form owns for a failure, by the problem code; never the server's own text. */
export function strainError(error: unknown): string {
  if (isApiError(error, 422) && error.code === 'lab_authorisation_required') return PERMIT_REFUSED
  if (isApiError(error) && error.code === 'risk_group_4_refused') return RISK_GROUP_4_REFUSED
  if (isApiError(error) && error.code === 'risk_group_above_box_cap') return RISK_GROUP_ABOVE_BOX_CAP
  if (isApiError(error, 409) && error.code === 'accession_taken') return 'Another strain took this number at the same moment. Save again.'
  if (isApiError(error, 409) && error.code === 'restriction_ended') return 'This restriction has ended already. Reload to see it.'
  return errorMessage(error)
}

/** The field a 422 names (`restrictions.1.kind`), if any. */
export function problemField(error: unknown): string | undefined {
  if (!isApiError(error)) return undefined
  return readProblem(error.body)?.errors?.find((e) => e.attr !== null)?.attr ?? undefined
}
