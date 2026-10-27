import { z } from 'zod'
import type { components } from '@/api/schema'
import { pageDefaults } from '@/lib/paging'

export type Reveal = components['schemas']['RevealLogEntry']
export type RevealPerson = components['schemas']['RevealPerson']

/** A Czech day as the API takes it. The server checks the date itself (400 for 2026-02-30). */
const DAY = /^\d{4}-\d{2}-\d{2}$/
const day = z.string().regex(DAY)

export const revealListDefaults = { ...pageDefaults, since: undefined, until: undefined, person: undefined }
export const revealListSearch = z.object({
  limit: z.number().int().min(1).max(200).default(pageDefaults.limit).catch(pageDefaults.limit),
  offset: z.number().int().min(0).default(pageDefaults.offset).catch(pageDefaults.offset),
  since: day.optional().catch(undefined),
  until: day.optional().catch(undefined),
  person: z.uuid().optional().catch(undefined),
})
export type RevealListParams = z.output<typeof revealListSearch>
export type RevealFilters = Omit<RevealListParams, 'limit' | 'offset'>

export const isDay = (text: string) => DAY.test(text)

/**
 * Who revealed, as the members table names people: the name and the username. An erased person
 * (ADR 0005) is only "Erased person": the row keeps a tombstone, which names nobody.
 */
export function personName(person: RevealPerson | null): string {
  if (person === null) return 'Not a person'
  if (person.erased) return 'Erased person'
  const name = [person.first_name, person.last_name].filter(Boolean).join(' ')
  return name === '' ? person.username : `${name} (${person.username})`
}

/** The first and the last day of the month of `today`, as YYYY-MM-DD in the browser's calendar. */
const pad = (n: number) => String(n).padStart(2, '0')

export function monthOf(today: Date): { since: string; until: string } {
  const year = today.getFullYear()
  const month = today.getMonth() + 1
  const last = new Date(year, month, 0).getDate()
  return { since: `${year}-${pad(month)}-01`, until: `${year}-${pad(month)}-${pad(last)}` }
}
