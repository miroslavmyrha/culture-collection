import { useQuery } from '@tanstack/react-query'
import { mediaListOptions } from '@/lib/growth'

export const useMediaList = (labId: string) => useQuery(mediaListOptions(labId))
