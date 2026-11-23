import { randomBytes } from 'node:crypto'

/**
 * A name part for the data one spec file makes in one run (#288). The clock alone is not enough:
 * workers load spec files in parallel, and two files took the same millisecond, so the same id.
 * Lowercase letters and digits, so it is found by search as typed.
 */
export const runId = () => Date.now().toString(36) + randomBytes(3).toString('hex')
