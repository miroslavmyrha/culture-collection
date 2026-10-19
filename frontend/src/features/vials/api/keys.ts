/**
 * Per lab and strain: a write invalidates the strain's material (its passages, batches and
 * vials), because a preservation adds to all three and a revival to two of them, and the grid
 * content of every box of the lab (boxGrids), because it may put a vial in a box or take one
 * out, and the page does not know which box held it. A write from the box grid invalidates the
 * whole lab: the vial may belong to any strain and come from another box. Both features' data
 * live under these keys, so no key root outside the feature is needed. Revealed locations are
 * never cached (useRevealLocation).
 */
export const vialKeys = {
  all: ['vials'] as const,
  lab: (labId: string) => [...vialKeys.all, labId] as const,
  strain: (labId: string, strainId: string) => [...vialKeys.lab(labId), 'strain', strainId] as const,
  passages: (labId: string, strainId: string) => [...vialKeys.strain(labId, strainId), 'passages'] as const,
  batches: (labId: string, strainId: string) => [...vialKeys.strain(labId, strainId), 'batches'] as const,
  vials: (labId: string, strainId: string) => [...vialKeys.strain(labId, strainId), 'vials'] as const,
  boxes: (labId: string) => [...vialKeys.lab(labId), 'boxes'] as const,
  boxGrids: (labId: string) => [...vialKeys.lab(labId), 'box'] as const,
  box: (labId: string, boxId: string) => [...vialKeys.boxGrids(labId), boxId] as const,
}
