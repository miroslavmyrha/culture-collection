import { sharedKeys } from '@/lib/shared-keys'
import type { PageParams } from '../schemas'

/**
 * Hierarchical. Every write invalidates all(): a role change can change my own role, which
 * the lab list, the lab and its members all show.
 */
export const labKeys = {
  all: ['labs'] as const,
  lists: () => [...labKeys.all, 'list'] as const,
  list: (params: PageParams) => [...labKeys.lists(), params] as const,
  details: () => [...labKeys.all, 'detail'] as const,
  detail: (labId: string) => [...labKeys.details(), labId] as const,
  members: sharedKeys.members,
  memberList: (labId: string, params: PageParams) => [...labKeys.members(labId), params] as const,
  /** Who may see where the lab's regulated strains are (ADR 0009): managers only. */
  locationGrants: (labId: string) => [...labKeys.detail(labId), 'location-grants'] as const,
  /** The VRAT access list with its history (act 281/2002 Sb., § 14a(4)): managers only. */
  vratAccess: (labId: string) => [...labKeys.detail(labId), 'vrat-access'] as const,
}
