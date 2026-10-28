import { queryOptions } from '@tanstack/react-query'
import { api, unwrap } from './api'

/**
 * Key roots of data that more than one feature reads or changes. A feature builds its own keys
 * on these roots, and a write in one feature invalidates another feature's data through them:
 * the import boundaries forbid importing another feature's keys. The writes that cross:
 *
 * - a strain write (a restriction added or ended, the risk group, a new taxon) changes how its
 *   vials show (location masked or not, can_reveal) and what the box grids show: strainMaterial
 *   and boxGrids;
 * - a storage write changes the units the vial forms offer (storageUnits, the same entry as the
 *   storage tree) and the paths and sizes in vial locations and box grids: material;
 * - a location grant given or revoked changes can_reveal for its holder: material;
 * - accepting a deposit creates a strain: strainLists;
 * - a new terms version of an accepted deposit changes its strain's terms and history:
 *   strainTerms and strainHistory;
 * - a medium renamed or retired changes how it shows on the strains and passages that use it:
 *   strains and material;
 * - a deposit or a request that changes what waits (received, checked, decided, shipped) changes
 *   Home and the counts on the lab tabs: overview;
 * - a strain that leaves the collection (#20) cancels its open requests and marks its vials for
 *   destruction: requests, strainMaterial, boxGrids, strainLists and overview;
 * - a reveal of a regulated vial's place adds a row to the lab's reveal log (#83): reveals.
 *
 * Shared roots rather than invalidation in the page: the mutation names every key it changes
 * and stays pending until all of them are fresh, wherever the dialog that runs it is mounted.
 */
export const sharedKeys = {
  strains: (labId: string) => ['strains', labId] as const,
  strainLists: (labId: string) => [...sharedKeys.strains(labId), 'list'] as const,
  storage: (labId: string) => ['storage', labId] as const,
  /** Every storage unit of the lab, in tree order: the storage tree and the vials' box choices. */
  storageUnits: (labId: string) => [...sharedKeys.storage(labId), 'tree'] as const,
  /** Passages, batches, vials and box grids of the lab. */
  material: (labId: string) => ['vials', labId] as const,
  strainMaterial: (labId: string, strainId: string) => [...sharedKeys.material(labId), 'strain', strainId] as const,
  boxGrids: (labId: string) => [...sharedKeys.material(labId), 'box'] as const,
  /**
   * A strain's history (#19), under its material: every write that changes the material or the
   * strain invalidates the material root, and with it the lines that write added.
   */
  strainHistory: (labId: string, strainId: string) => [...sharedKeys.strainMaterial(labId, strainId), 'history'] as const,
  /** A strain's terms of use (#19): a new terms version of its deposit changes them. */
  strainTerms: (labId: string, strainId: string) => [...sharedKeys.strains(labId), 'terms', strainId] as const,
  /** The lab's media (#79): the strain and passage dialogs choose from them, the media screen manages them. */
  media: (labId: string) => ['media', labId] as const,
  mediaList: (labId: string, params: { limit: number; offset: number }) => [...sharedKeys.media(labId), 'list', params] as const,
  /** The lab's requests, lists and details (#18): a deaccession cancels some (#20). */
  requests: (labId: string) => ['requests', labId] as const,
  /** The lab's reveal log (#83): who revealed where a regulated vial is. */
  reveals: (labId: string) => ['reveals', labId] as const,
  /** What waits for the signed-in person across their labs, and each lab's figures (#69). */
  overview: () => ['overview'] as const,
}

/**
 * The lab's storage units as the API answers. One key holds one shape: a feature that needs
 * another shape derives it with `select`, never with its own queryFn under this key.
 */
export const storageUnitsOptions = (labId: string) =>
  queryOptions({
    queryKey: sharedKeys.storageUnits(labId),
    // The whole tree of the lab in one response, in tree order (ADR 0008, D14).
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/labs/{lab_public_id}/storage-units/', { signal, params: { path: { lab_public_id: labId } } })),
  })
