import type { z } from 'zod'

/** A cross-field rule: when it holds, the field at the path gets the message. */
export type Rule<T> = readonly [holds: (form: T) => boolean, path: string, message: string]

/** Adds the issue of every rule that holds, in the order the rules are listed. */
export function addIssues<T>(rules: readonly Rule<T>[], form: T, ctx: z.RefinementCtx) {
  for (const [holds, path, message] of rules) if (holds(form)) ctx.addIssue({ code: 'custom', path: [path], message })
}
