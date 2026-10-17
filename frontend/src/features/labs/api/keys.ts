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
  members: (labId: string) => [...labKeys.detail(labId), 'members'] as const,
  memberList: (labId: string, params: PageParams) => [...labKeys.members(labId), params] as const,
}
