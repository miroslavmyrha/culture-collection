import { sharedKeys } from '@/lib/shared-keys'
import type { PageParams } from '@/lib/paging'
import type { StrainListParams } from '../schemas'

/**
 * Hierarchical, per lab: a write invalidates the lab's lists() and sets its detail. Every
 * filter and page value is in list(params), so two filters never share a cache entry. The lab
 * and its lists are shared roots (lib/shared-keys): accepting a deposit adds a strain.
 */
export const strainKeys = {
  all: ['strains'] as const,
  lab: sharedKeys.strains,
  lists: sharedKeys.strainLists,
  list: (labId: string, params: StrainListParams) => [...strainKeys.lists(labId), params] as const,
  details: (labId: string) => [...strainKeys.lab(labId), 'detail'] as const,
  detail: (labId: string, strainId: string) => [...strainKeys.details(labId), strainId] as const,
  /** Shared roots (#19): a deposit's new terms version changes the terms, any write the history. */
  terms: sharedKeys.strainTerms,
  history: (labId: string, strainId: string, page: PageParams) => [...sharedKeys.strainHistory(labId, strainId), page] as const,
}

/** Taxa are global: no lab in their keys. */
export const taxonKeys = {
  all: ['taxa'] as const,
  search: (text: string) => [...taxonKeys.all, 'search', text] as const,
  detail: (taxonId: string) => [...taxonKeys.all, 'detail', taxonId] as const,
}
