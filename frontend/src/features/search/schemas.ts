import type { components } from '@/api/schema'
import type { Tone } from '@/components/ui'
import { DEPOSIT_TONES, REQUEST_TONES, STRAIN_TONES, VIAL_TONES } from '@/lib/tones'

export type SearchGroup = components['schemas']['SearchGroup']
export type SearchHit = components['schemas']['SearchHit']
export type Kind = SearchGroup['kind']
type Location = NonNullable<SearchHit['location']>

/** The server finds nothing below this many characters (search/selectors.py, SHORTEST). */
export const SHORTEST = 2
/** Results as you type: the request goes out once typing pauses this long. */
export const DEBOUNCE_MS = 250

/** Spaces folded the way the server folds them, so the key and the request agree. */
export const normalise = (text: string) => text.split(/\s+/).filter(Boolean).join(' ')

export const KIND_TITLES: Record<Kind, string> = { strain: 'Strains', vial: 'Vials', deposit: 'Deposits', request: 'Requests' }
const KIND_NOUNS: Record<Kind, [string, string]> = { strain: ['strain', 'strains'], vial: ['vial', 'vials'], deposit: ['deposit', 'deposits'], request: ['request', 'requests'] }

/**
 * Each kind's status words, as its own pages say them. The search feature may not import those
 * features, so app/search-labels.test.ts compares these with theirs.
 */
export const STATUS_LABELS: Record<Kind, Record<string, string>> = {
  strain: { pending: 'Pending', active: 'Active', restricted: 'Restricted', deaccessioned: 'Deaccessioned' },
  vial: {
    available: 'Available',
    reserved: 'Reserved',
    consumed: 'Consumed',
    quarantined: 'Quarantined',
    to_destroy: 'To destroy',
    destroyed: 'Destroyed',
    lost: 'Lost',
    distributed: 'Distributed',
    entered_in_error: 'Entered in error',
  },
  deposit: { received: 'Received', checking: 'Checking', accepted: 'Accepted', rejected: 'Rejected' },
  request: {
    submitted: 'Waiting for a decision',
    approved: 'Approved, vials reserved',
    awaiting_confirmation: 'Shipment prepared, waiting for a second person',
    shipped: 'Shipped',
    rejected: 'Rejected',
    cancelled: 'Cancelled',
  },
}
const TONES: Record<Kind, Record<string, Tone>> = { strain: STRAIN_TONES, vial: VIAL_TONES, deposit: DEPOSIT_TONES, request: REQUEST_TONES }

export const statusLabel = (kind: Kind, status: string) => STATUS_LABELS[kind][status] ?? status
export const statusTone = (kind: Kind, status: string): Tone | undefined => TONES[kind][status]

export const locationText = (l: Location) => `${l.path.join(' / ')}, ${l.label}`
export const MASKED = 'Place hidden: regulated strain'

/** The identifier a person reads first: the number or label, or what stands in for it. */
export function identifierOf(kind: Kind, hit: SearchHit): string {
  if (hit.identifier !== null) return hit.identifier
  return kind === 'deposit' ? 'No strain yet' : 'Pending strain'
}

/** The second line: what it is, and for a vial where it is, or that its place is hidden. */
export function detailOf(kind: Kind, hit: SearchHit): string {
  const parts = [hit.title]
  if (kind === 'vial') parts.push(hit.location ? locationText(hit.location) : hit.location_masked ? MASKED : 'Not in a box')
  if (hit.detail) parts.push(hit.detail)
  return parts.join(', ')
}

/** The whole option as one sentence (a name assembled from parts reads with stray commas). */
export const optionName = (kind: Kind, hit: SearchHit) => `${identifierOf(kind, hit)}, ${hit.lab_code}, ${statusLabel(kind, hit.status)}. ${detailOf(kind, hit)}`

/** Where a hit opens: a strain, a vial on its strain's Material tab, a deposit, a request. */
export type Target =
  | { to: '/labs/$labId/strains/$strainId'; params: { labId: string; strainId: string } }
  | { to: '/labs/$labId/strains/$strainId/material'; params: { labId: string; strainId: string }; search: { vial: string } }
  | { to: '/labs/$labId/deposits/$depositId'; params: { labId: string; depositId: string } }
  | { to: '/labs/$labId/requests/$requestId'; params: { labId: string; requestId: string } }
  | { to: '/labs/$labId/strains' | '/labs/$labId/deposits' | '/labs/$labId/requests'; params: { labId: string }; search: { search: string } }

export function targetOf(kind: Kind, hit: SearchHit): Target | null {
  const labId = hit.lab
  if (kind === 'strain') return { to: '/labs/$labId/strains/$strainId', params: { labId, strainId: hit.public_id } }
  if (kind === 'vial') return hit.strain === null ? null : { to: '/labs/$labId/strains/$strainId/material', params: { labId, strainId: hit.strain }, search: { vial: hit.public_id } }
  if (kind === 'deposit') return { to: '/labs/$labId/deposits/$depositId', params: { labId, depositId: hit.public_id } }
  void (kind satisfies 'request')
  return { to: '/labs/$labId/requests/$requestId', params: { labId, requestId: hit.public_id } }
}

const LISTS = { strain: '/labs/$labId/strains', deposit: '/labs/$labId/deposits', request: '/labs/$labId/requests' } as const

/** One entry of the listbox: a hit, or the list of all matches of a kind in one lab. */
export type Entry =
  | { type: 'hit'; id: string; kind: Kind; hit: SearchHit; name: string; target: Target | null }
  | { type: 'all'; id: string; kind: Kind; name: string; target: Target }

/**
 * The entries of each group in the server's order. A kind with a list page (vials have none)
 * ends with a link to that list filtered by the text, per lab, when it holds more than the
 * group shows of that lab.
 */
export function entriesOf(groups: readonly SearchGroup[], text: string): { group: SearchGroup; entries: Entry[] }[] {
  return groups.map((group) => {
    const entries: Entry[] = group.hits.map((hit) => ({ type: 'hit', id: `${group.kind}-${hit.public_id}`, kind: group.kind, hit, name: optionName(group.kind, hit), target: targetOf(group.kind, hit) }))
    if (group.kind !== 'vial') {
      const to = LISTS[group.kind]
      for (const lab of group.labs) {
        const shown = group.hits.filter((hit) => hit.lab === lab.lab).length
        if (lab.total <= shown) continue
        const [, plural] = KIND_NOUNS[group.kind]
        entries.push({ type: 'all', id: `${group.kind}-all-${lab.lab}`, kind: group.kind, name: `All ${lab.total} ${plural} in ${lab.lab_code}`, target: { to, params: { labId: lab.lab }, search: { search: text } } })
      }
    }
    return { group, entries }
  })
}

/** "Strains, 12 found" for the group's label. */
export function groupLabel(group: SearchGroup): string {
  const [one, many] = KIND_NOUNS[group.kind]
  return `${KIND_TITLES[group.kind]}, ${group.total} ${group.total === 1 ? one : many}`
}

/** The one hit the text names (a scanned barcode, a number), or null when none or several do. */
export function exactHit(groups: readonly SearchGroup[]): { kind: Kind; hit: SearchHit } | null {
  const exact = groups.flatMap((group) => group.hits.filter((hit) => hit.exact).map((hit) => ({ kind: group.kind, hit })))
  return exact.length === 1 ? (exact[0] ?? null) : null
}

/** What the live region says once results are in. */
export function resultsSummary(groups: readonly SearchGroup[]): string {
  const total = groups.reduce((sum, group) => sum + group.total, 0)
  if (total === 0) return 'No results.'
  return `${total} ${total === 1 ? 'result' : 'results'}: ${groups.map((g) => `${g.total} ${KIND_NOUNS[g.kind][g.total === 1 ? 0 : 1]}`).join(', ')}.`
}
