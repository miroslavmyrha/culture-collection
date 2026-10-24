import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { PageParams } from '@/lib/paging'
import type { StrainListParams } from '../schemas'
import { strainKeys, taxonKeys } from './keys'

/** One options object for the hook, the route loader and typed cache access in tests. */
export const strainListOptions = (labId: string, params: StrainListParams) =>
  queryOptions({
    queryKey: strainKeys.list(labId, params),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/strains/', { signal, params: { path: { lab_public_id: labId }, query: params } })),
    // The previous page or filter stays on screen while the next one loads.
    placeholderData: keepPreviousData,
  })

export const strainDetailOptions = (labId: string, strainId: string) =>
  queryOptions({
    queryKey: strainKeys.detail(labId, strainId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/strains/{public_id}/', { signal, params: { path: { lab_public_id: labId, public_id: strainId } } }),
      ),
  })

/** Every version of the strain's terms of use, newest first, with the MTA each names (#19). */
export const strainTermsOptions = (labId: string, strainId: string) =>
  queryOptions({
    queryKey: strainKeys.terms(labId, strainId),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/strains/{public_id}/terms/', { signal, params: { path: { lab_public_id: labId, public_id: strainId } } })),
  })

/** A page of what happened to the strain, newest first (#19). */
export const strainHistoryOptions = (labId: string, strainId: string, page: PageParams) =>
  queryOptions({
    queryKey: strainKeys.history(labId, strainId, page),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/strains/{public_id}/history/', {
          signal,
          params: { path: { lab_public_id: labId, public_id: strainId }, query: page },
        }),
      ),
    // The page before stays on screen while the next one loads.
    placeholderData: keepPreviousData,
  })

export const TAXON_PAGE = 20

export const taxonSearchOptions = (text: string) =>
  queryOptions({
    queryKey: taxonKeys.search(text),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/taxa/', { signal, params: { query: { search: text, limit: TAXON_PAGE } } })),
    placeholderData: keepPreviousData,
    // Taxa change rarely and only through staff: a minute is fresh enough.
    staleTime: 60_000,
  })

export const taxonOptions = (taxonId: string) =>
  queryOptions({
    queryKey: taxonKeys.detail(taxonId),
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/taxa/{public_id}/', { signal, params: { path: { public_id: taxonId } } })),
    staleTime: 60_000,
  })

export function useStrainList(labId: string, params: StrainListParams) {
  return useQuery(strainListOptions(labId, params))
}

export function useStrain(labId: string, strainId: string) {
  return useQuery(strainDetailOptions(labId, strainId))
}

export function useStrainTerms(labId: string, strainId: string) {
  return useQuery(strainTermsOptions(labId, strainId))
}

export function useStrainHistory(labId: string, strainId: string, page: PageParams) {
  return useQuery(strainHistoryOptions(labId, strainId, page))
}

export function useTaxonSearch(text: string, enabled: boolean) {
  return useQuery({ ...taxonSearchOptions(text), enabled })
}

export function useTaxon(taxonId: string | undefined) {
  return useQuery({ ...taxonOptions(taxonId ?? ''), enabled: taxonId !== undefined })
}
