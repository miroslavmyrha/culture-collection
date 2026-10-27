import { z } from 'zod'
import { reasonSchema } from '@/lib/growth'

export type { Medium } from '@/lib/growth'

const required = (message: string) => z.string().trim().min(1, message)

// Limits mirror the server (name 100, reference 200); the server still decides.
export const mediumSchema = z.object({
  name: required('Enter the name of the medium').max(100, 'Use at most 100 characters'),
  composition_reference: z.string().trim().max(200, 'Use at most 200 characters'),
})
export type MediumForm = z.input<typeof mediumSchema>

export const retireSchema = z.object({ reason: reasonSchema })
export type RetireForm = z.input<typeof retireSchema>
