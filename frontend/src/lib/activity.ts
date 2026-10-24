// How a line of the audit trail reads on Home and on a strain's history (#69, #19).

/**
 * The actor as the audit trail labels it (ADR 0005): the reader is "You", a user is the start of
 * the public id in their label, a system actor its own label. Never a name.
 */
export function actorLabel(actor: string): string {
  if (actor === 'you') return 'You'
  if (actor.startsWith('user:')) return `user ${actor.slice('user:'.length, 'user:'.length + 8)}`
  return actor
}

/** A moment as people here read it: 2026-10-23 14:05, local time. */
export const moment = (iso: string) => new Date(iso).toLocaleString('sv', { dateStyle: 'short', timeStyle: 'short' })
