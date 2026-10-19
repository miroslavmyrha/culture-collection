/**
 * Per lab: a write sets the unit's detail and invalidates the rest of the lab's storage, because
 * a move or a new unit changes the tree and the breadcrumbs and contents of other units.
 */
export const storageKeys = {
  all: ['storage'] as const,
  lab: (labId: string) => [...storageKeys.all, labId] as const,
  tree: (labId: string) => [...storageKeys.lab(labId), 'tree'] as const,
  details: (labId: string) => [...storageKeys.lab(labId), 'detail'] as const,
  detail: (labId: string, unitId: string) => [...storageKeys.details(labId), unitId] as const,
}

/** Box types are global: no lab in their key. */
export const boxTypeKeys = {
  all: ['box-types'] as const,
}
