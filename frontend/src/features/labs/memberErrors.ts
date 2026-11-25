import { errorMessage, isApiError } from '@/lib/api'

const MESSAGES = new Map<string, string>(
  Object.entries({
    last_manager: 'A lab needs at least one active manager. Make another member manager first.',
    grant_above_own_role: 'You cannot change a role above your own.',
    already_granted: 'This member may see regulated locations already. Reload to see it.',
    grant_revoked: 'This grant has been revoked already. Reload to see it.',
    // #267: a second manager confirms, never the proposer or the holder.
    grant_confirmed: 'Another manager confirmed this grant already. Reload to see it.',
    confirm_own_proposal: 'You proposed this grant: another manager confirms it.',
    confirm_own_grant: 'This grant is your own: another manager confirms it.',
  }),
)

/** The messages a member dialog owns, by the problem code; never the server's own text. */
export function memberError(error: unknown): string {
  const own = isApiError(error) && error.code ? MESSAGES.get(error.code) : undefined
  return own ?? errorMessage(error)
}
