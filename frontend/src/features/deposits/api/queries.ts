import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { DepositListParams, DepositorListParams } from '../schemas'
import { depositKeys, depositorKeys, mtaKeys } from './keys'

/** One options object for the hook, the route loader and typed cache access in tests. */
export const depositListOptions = (labId: string, params: DepositListParams) =>
  queryOptions({
    queryKey: depositKeys.list(labId, params),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/deposits/', { signal, params: { path: { lab_public_id: labId }, query: params } })),
    placeholderData: keepPreviousData,
  })

export const depositDetailOptions = (labId: string, depositId: string) =>
  queryOptions({
    queryKey: depositKeys.detail(labId, depositId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/deposits/{public_id}/', { signal, params: { path: { lab_public_id: labId, public_id: depositId } } }),
      ),
  })

export const depositorListOptions = (labId: string, params: DepositorListParams) =>
  queryOptions({
    queryKey: depositorKeys.list(labId, params),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/depositors/', { signal, params: { path: { lab_public_id: labId }, query: params } })),
    placeholderData: keepPreviousData,
  })

export const depositorOptions = (labId: string, depositorId: string) =>
  queryOptions({
    queryKey: depositorKeys.detail(labId, depositorId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/depositors/{public_id}/', { signal, params: { path: { lab_public_id: labId, public_id: depositorId } } }),
      ),
  })

/** A lab has a few MTA codes with a few versions each: one page of 200 holds them. */
export const MTA_ALL = { limit: 200, offset: 0 }

export const mtaListOptions = (labId: string, params: { limit: number; offset: number } = MTA_ALL) =>
  queryOptions({
    queryKey: mtaKeys.list(labId, params),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/labs/{lab_public_id}/mta-templates/', { signal, params: { path: { lab_public_id: labId }, query: params } })),
    placeholderData: keepPreviousData,
  })

export const mtaDetailOptions = (labId: string, templateId: string) =>
  queryOptions({
    queryKey: mtaKeys.detail(labId, templateId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/labs/{lab_public_id}/mta-templates/{public_id}/', { signal, params: { path: { lab_public_id: labId, public_id: templateId } } }),
      ),
  })

export const useDepositList = (labId: string, params: DepositListParams) => useQuery(depositListOptions(labId, params))
export const useDeposit = (labId: string, depositId: string) => useQuery(depositDetailOptions(labId, depositId))
export const useDepositorList = (labId: string, params: DepositorListParams, enabled = true) =>
  useQuery({ ...depositorListOptions(labId, params), enabled })
export const useDepositor = (labId: string, depositorId: string | undefined) =>
  useQuery({ ...depositorOptions(labId, depositorId ?? ''), enabled: depositorId !== undefined })
export const useMtaList = (labId: string, params?: { limit: number; offset: number }) => useQuery(mtaListOptions(labId, params))
export const useMtaTemplate = (labId: string, templateId: string | undefined) =>
  useQuery({ ...mtaDetailOptions(labId, templateId ?? ''), enabled: templateId !== undefined })
