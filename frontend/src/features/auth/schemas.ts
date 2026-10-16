import { z } from 'zod'

export const loginSchema = z.object({
  username: z.string().trim().min(1, 'Enter your username').max(150),
  password: z.string().min(1, 'Enter your password').max(256),
})
export type LoginInput = z.infer<typeof loginSchema>
