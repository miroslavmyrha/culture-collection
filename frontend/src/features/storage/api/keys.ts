import { sharedKeys } from '@/lib/shared-keys'

/**
 * Per lab: a write sets the unit's detail and invalidates the rest of the lab's storage, because
 * a move or a new unit changes the tree and the breadcrumbs and contents of other units. The lab
 * and its tree are shared roots (lib/shared-keys): the vials' box choices read the tree.
 */
export const storageKeys = {
  all: ['storage'] as const,
  lab: sharedKeys.storage,
  tree: sharedKeys.storageUnits,
  details: (labId: string) => [...storageKeys.lab(labId), 'detail'] as const,
  detail: (labId: string, unitId: string) => [...storageKeys.details(labId), unitId] as const,
}

/** Box types are global: no lab in their key. */
export const boxTypeKeys = {
  all: ['box-types'] as const,
}
