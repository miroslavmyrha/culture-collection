import type { components } from '@/api/schema'
import type { Problem, ProblemError } from '@/lib/api'

export type Me = components['schemas']['MeOutput']
export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] }

// A counter, not random values: unique and repeatable.
let seq = 0
const next = () => ++seq
export const resetFactories = () => {
  seq = 0
}
const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`

export function makeMe(overrides: Partial<Me> = {}): Me {
  const n = next()
  return { public_id: uuid(n), username: `user-${n}`, first_name: '', last_name: '', email: `user-${n}@example.org`, ...overrides }
}

export function page<T>(results: T[], overrides: Partial<Paginated<T>> = {}): Paginated<T> {
  return { count: results.length, next: null, previous: null, results, ...overrides }
}

/** A problem-details body as the backend sends it for 4xx. */
export function problem(status: number, overrides: Partial<Problem> = {}): Problem {
  return { type: 'about:blank', title: 'Error', status, detail: 'Request failed.', code: 'error', ...overrides }
}

export function validationProblem(errors: ProblemError[]): Problem {
  return problem(400, { title: 'Invalid input.', detail: 'Invalid input.', code: 'invalid', errors })
}
