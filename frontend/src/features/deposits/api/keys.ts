import type { DepositListParams, DepositorListParams } from '../schemas'

/**
 * Hierarchical, per lab: a write sets the detail it answers with and invalidates the lab's
 * lists. Every filter and page value is in list(params).
 */
export const depositKeys = {
  all: ['deposits'] as const,
  lab: (labId: string) => [...depositKeys.all, labId] as const,
  lists: (labId: string) => [...depositKeys.lab(labId), 'list'] as const,
  list: (labId: string, params: DepositListParams) => [...depositKeys.lists(labId), params] as const,
  details: (labId: string) => [...depositKeys.lab(labId), 'detail'] as const,
  detail: (labId: string, depositId: string) => [...depositKeys.details(labId), depositId] as const,
}

export const depositorKeys = {
  all: ['depositors'] as const,
  lab: (labId: string) => [...depositorKeys.all, labId] as const,
  lists: (labId: string) => [...depositorKeys.lab(labId), 'list'] as const,
  list: (labId: string, params: DepositorListParams) => [...depositorKeys.lists(labId), params] as const,
}

export const mtaKeys = {
  all: ['mta-templates'] as const,
  lab: (labId: string) => [...mtaKeys.all, labId] as const,
  lists: (labId: string) => [...mtaKeys.lab(labId), 'list'] as const,
  list: (labId: string, params: { limit: number; offset: number }) => [...mtaKeys.lists(labId), params] as const,
  detail: (labId: string, templateId: string) => [...mtaKeys.lab(labId), 'detail', templateId] as const,
}
