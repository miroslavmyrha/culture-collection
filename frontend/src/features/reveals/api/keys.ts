import { sharedKeys } from '@/lib/shared-keys'
import type { RevealListParams } from '../schemas'

/** The lab's reveal log (#83), a page per filter. A shared root: a reveal on a strain page adds a row. */
export const revealKeys = {
  lab: sharedKeys.reveals,
  list: (labId: string, params: RevealListParams) => [...revealKeys.lab(labId), params] as const,
}
