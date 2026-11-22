import { startAuthentication, startRegistration } from '@simplewebauthn/browser'
import type { PublicKeyCredentialCreationOptionsJSON, PublicKeyCredentialRequestOptionsJSON } from '@simplewebauthn/browser'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, ensureCsrf, unwrap } from '@/lib/api'
import { resetSessionCache } from './cache'
import { authKeys } from './keys'

export type Me = components['schemas']['MeOutput']
export type Enrolled = components['schemas']['EnrolledOutput']
export type Method = components['schemas']['MethodsEnum']
export type Factors = components['schemas']['FactorsOutput']

/** The server's WebAuthn options, read without trusting them: an object with a challenge. */
const hasChallenge = (value: unknown): value is { challenge: string } =>
  typeof value === 'object' && value !== null && typeof Reflect.get(value, 'challenge') === 'string'

function isCreation(value: unknown): value is PublicKeyCredentialCreationOptionsJSON {
  return hasChallenge(value) && typeof Reflect.get(value, 'rp') === 'object'
}

function isRequest(value: unknown): value is PublicKeyCredentialRequestOptionsJSON {
  return hasChallenge(value)
}

export function creationOptions(value: unknown): PublicKeyCredentialCreationOptionsJSON {
  if (!isCreation(value)) throw new Error('The server sent no key options.')
  return value
}

export function requestOptions(value: unknown): PublicKeyCredentialRequestOptionsJSON {
  if (!isRequest(value)) throw new Error('The server sent no key options.')
  return value
}

export const factorKeys = {
  all: [...authKeys.all, 'factors'] as const,
  mine: () => [...factorKeys.all, 'mine'] as const,
}

/** The second factor of the sign-in, or again for a signed-in user (a step-up, #176). */
export function useCodeSignIn() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: components['schemas']['CodeInputRequest']) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/auth/second-factor/', { body }))
    },
    meta: { handlesError: true },
    onSuccess: (me) => signedIn(qc, me),
  })
}

export function useKeySignIn() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await ensureCsrf()
      const { options } = await unwrap(api.POST('/api/v1/auth/second-factor/key/options/'))
      const credential = await startAuthentication({ optionsJSON: requestOptions(options) })
      return unwrap(api.POST('/api/v1/auth/second-factor/key/', { body: { credential } }))
    },
    meta: { handlesError: true },
    onSuccess: (me) => signedIn(qc, me),
  })
}

/** A step-up keeps the cache (the same user); the end of a sign-in starts a fresh one. */
function signedIn(qc: ReturnType<typeof useQueryClient>, me: Me) {
  const before = qc.getQueryData<Me | null>(authKeys.me())
  if (before?.public_id === me.public_id) void qc.invalidateQueries({ queryKey: factorKeys.mine() })
  else resetSessionCache(qc, me)
}

function enrolled(qc: ReturnType<typeof useQueryClient>, result: Enrolled) {
  if (result.me) resetSessionCache(qc, result.me)
  else void qc.invalidateQueries({ queryKey: factorKeys.mine() })
}

export function useKeyEnrol() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (name: string) => {
      await ensureCsrf()
      const { options } = await unwrap(api.POST('/api/v1/auth/factors/keys/options/'))
      const credential = await startRegistration({ optionsJSON: creationOptions(options) })
      return unwrap(api.POST('/api/v1/auth/factors/keys/', { body: { credential, name } }))
    },
    meta: { handlesError: true },
    onSuccess: (result) => enrolled(qc, result),
  })
}

export function useTotpSetup() {
  return useMutation({
    mutationFn: async () => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/auth/factors/totp/setup/'))
    },
    meta: { handlesError: true },
  })
}

export function useTotpEnrol() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (code: string) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/auth/factors/totp/', { body: { code } }))
    },
    meta: { handlesError: true },
    onSuccess: (result) => enrolled(qc, result),
  })
}

export function useMyFactors() {
  return useQuery({ queryKey: factorKeys.mine(), queryFn: () => unwrap(api.GET('/api/v1/auth/factors/')) })
}

export function useRemoveKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (publicId: string) => unwrap(api.DELETE('/api/v1/auth/factors/keys/{public_id}/', { params: { path: { public_id: publicId } } })),
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: factorKeys.mine() }),
  })
}

export function useRemoveTotp() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/auth/factors/totp/remove/')),
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: factorKeys.mine() }),
  })
}

export function useNewRecoveryCodes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/factors/recovery-codes/')),
    meta: { handlesError: true },
    onSuccess: () => qc.invalidateQueries({ queryKey: factorKeys.mine() }),
  })
}

/** The manager's one-time code before the first enrolment (#176). */
export function useEnrolmentCode() {
  return useMutation({
    mutationFn: async (code: string) => {
      await ensureCsrf()
      return unwrap(api.POST('/api/v1/auth/enrolment-code/', { body: { code } }))
    },
    meta: { handlesError: true },
  })
}
