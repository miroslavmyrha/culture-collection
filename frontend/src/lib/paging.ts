import { z } from 'zod'

/** A page of a list in the URL. Defaults stay out of the URL. A bad value falls back to them. */
export const pageDefaults = { limit: 25, offset: 0 }
export const pageSearch = z.object({
  limit: z.number().int().min(1).max(200).default(pageDefaults.limit).catch(pageDefaults.limit),
  offset: z.number().int().min(0).default(pageDefaults.offset).catch(pageDefaults.offset),
})
export type PageParams = z.output<typeof pageSearch>
