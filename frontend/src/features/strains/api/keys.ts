import type { StrainListParams } from '../schemas'

/**
 * Hierarchical, per lab: a write invalidates the lab's lists() and sets its detail. Every
 * filter and page value is in list(params), so two filters never share a cache entry.
 */
export const strainKeys = {
  all: ['strains'] as const,
  lab: (labId: string) => [...strainKeys.all, labId] as const,
  lists: (labId: string) => [...strainKeys.lab(labId), 'list'] as const,
  list: (labId: string, params: StrainListParams) => [...strainKeys.lists(labId), params] as const,
  details: (labId: string) => [...strainKeys.lab(labId), 'detail'] as const,
  detail: (labId: string, strainId: string) => [...strainKeys.details(labId), strainId] as const,
}

/** Taxa are global: no lab in their keys. */
export const taxonKeys = {
  all: ['taxa'] as const,
  search: (text: string) => [...taxonKeys.all, 'search', text] as const,
  detail: (taxonId: string) => [...taxonKeys.all, 'detail', taxonId] as const,
}
