import type { VialPage } from '../schemas'
import { sharedKeys } from '@/lib/shared-keys'

/**
 * Per lab and strain: a write invalidates the strain's material (its passages, batches and
 * vials), because a preservation adds to all three and a revival to two of them, and the grid
 * content of every box of the lab (boxGrids), because it may put a vial in a box or take one
 * out, and the page does not know which box held it. A write from the box grid invalidates the
 * whole lab: the vial may belong to any strain and come from another box. The lab, a strain's
 * material and the box grids are shared roots (lib/shared-keys): strain, storage and lab writes
 * change them too. The box choices are the storage tree's entry (storageUnitsOptions). Revealed
 * locations are never cached (useRevealLocation).
 */
export const vialKeys = {
  all: ['vials'] as const,
  lab: sharedKeys.material,
  strain: sharedKeys.strainMaterial,
  passages: (labId: string, strainId: string) => [...vialKeys.strain(labId, strainId), 'passages'] as const,
  batches: (labId: string, strainId: string) => [...vialKeys.strain(labId, strainId), 'batches'] as const,
  vials: (labId: string, strainId: string) => [...vialKeys.strain(labId, strainId), 'vials'] as const,
  /** One page of the strain's vials, of one batch or of all (#72). */
  vialPage: (labId: string, strainId: string, page: VialPage) => [...vialKeys.vials(labId, strainId), page] as const,
  /** The checks of one batch, under its strain: a check, a release or a hold refreshes them with the rest. */
  checks: (labId: string, strainId: string, batchId: string) => [...vialKeys.strain(labId, strainId), 'checks', batchId] as const,
  boxGrids: sharedKeys.boxGrids,
  box: (labId: string, boxId: string) => [...vialKeys.boxGrids(labId), boxId] as const,
}
