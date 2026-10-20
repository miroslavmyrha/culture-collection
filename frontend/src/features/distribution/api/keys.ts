import { sharedKeys } from '@/lib/shared-keys'
import type { RequesterListParams, RequestListParams } from '../schemas'

/**
 * Hierarchical, per lab: a write sets the detail it answers with and invalidates the lab's
 * lists. Every filter and page value is in list(params).
 */
export const requestKeys = {
  all: ['requests'] as const,
  lab: (labId: string) => [...requestKeys.all, labId] as const,
  lists: (labId: string) => [...requestKeys.lab(labId), 'list'] as const,
  list: (labId: string, params: RequestListParams) => [...requestKeys.lists(labId), params] as const,
  details: (labId: string) => [...requestKeys.lab(labId), 'detail'] as const,
  detail: (labId: string, requestId: string) => [...requestKeys.details(labId), requestId] as const,
}

export const requesterKeys = {
  all: ['requesters'] as const,
  lab: (labId: string) => [...requesterKeys.all, labId] as const,
  lists: (labId: string) => [...requesterKeys.lab(labId), 'list'] as const,
  list: (labId: string, params: RequesterListParams) => [...requesterKeys.lists(labId), params] as const,
}

/** The strains a request line may name: the lab's strain list, a shared root (lib/shared-keys). */
export const strainChoiceKeys = {
  search: (labId: string, search: string) => [...sharedKeys.strainLists(labId), { limit: 20, offset: 0, search }] as const,
}
