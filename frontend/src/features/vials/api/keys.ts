/**
 * Per lab and strain: a write invalidates the strain's material (its passages, batches and
 * vials), because a preservation adds to all three and a revival to two of them. Revealed
 * locations are never cached (useRevealLocation).
 */
export const vialKeys = {
  all: ['vials'] as const,
  lab: (labId: string) => [...vialKeys.all, labId] as const,
  strain: (labId: string, strainId: string) => [...vialKeys.lab(labId), 'strain', strainId] as const,
  passages: (labId: string, strainId: string) => [...vialKeys.strain(labId, strainId), 'passages'] as const,
  batches: (labId: string, strainId: string) => [...vialKeys.strain(labId, strainId), 'batches'] as const,
  vials: (labId: string, strainId: string) => [...vialKeys.strain(labId, strainId), 'vials'] as const,
  boxes: (labId: string) => [...vialKeys.lab(labId), 'boxes'] as const,
}
