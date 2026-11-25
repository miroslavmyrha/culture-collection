import { useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { Alert, Button, Stack, Typography } from '@/components/ui'
import { type Factors, type Method, useMyFactors, useNewRecoveryCodes, useRemoveKey, useRemoveTotp } from '../api/factors'
import { EnrolForm } from './EnrolForm'
import { factorError } from '../factorErrors'
import { RecoveryCodes } from './RecoveryCodes'
import { SecondFactorForm } from './SecondFactorForm'

const methodsOf = (f: Factors): Method[] => [
  ...(f.security_keys.length > 0 ? (['security_key'] as const) : []),
  ...(f.totp ? (['totp'] as const) : []),
  ...(f.recovery_codes_left > 0 ? (['recovery_code'] as const) : []),
]

/**
 * The signed-in user's own second factors (#176). Changes need a second factor of the last
 * minutes: until then the page asks for one first. The last factor stays.
 */
export function FactorList() {
  const factors = useMyFactors()
  if (factors.data === undefined) {
    if (factors.isPending) return <Typography>Loading your second factors…</Typography>
    return <LoadError what="your second factors" error={factors.error} onRetry={() => void factors.refetch()} />
  }
  return <FactorsView factors={factors.data} />
}

function FactorsView({ factors }: { factors: Factors }) {
  const [codes, setCodes] = useState<string[] | null>(null)
  if (codes) return <RecoveryCodes codes={codes} onDone={() => setCodes(null)} doneLabel="Done" />
  return (
    <Stack spacing={3}>
      <Current factors={factors} />
      {factors.fresh ? <Changes factors={factors} onCodes={setCodes} /> : <StepUp factors={factors} />}
    </Stack>
  )
}

function Current({ factors }: { factors: Factors }) {
  return (
    <Stack spacing={1}>
      <Typography component="h2" variant="h6">
        Your second factors
      </Typography>
      <ul aria-label="Second factors">
        {factors.security_keys.map((key) => (
          <li key={key.public_id}>Security key: {key.name}</li>
        ))}
        {factors.totp && <li>Authenticator app</li>}
      </ul>
      <Typography>Recovery codes left: {factors.recovery_codes_left}</Typography>
    </Stack>
  )
}

function StepUp({ factors }: { factors: Factors }) {
  return (
    <Stack spacing={1}>
      <Typography>To change them, confirm with your second factor first.</Typography>
      <SecondFactorForm methods={methodsOf(factors)} onSignedIn={() => undefined} onRestart={() => undefined} />
    </Stack>
  )
}

function Changes({ factors, onCodes }: { factors: Factors; onCodes: (codes: string[]) => void }) {
  const removeKey = useRemoveKey()
  const removeTotp = useRemoveTotp()
  const newCodes = useNewRecoveryCodes()
  const last = factors.security_keys.length + (factors.totp ? 1 : 0) <= 1
  const failure = removeKey.error ?? removeTotp.error ?? newCodes.error
  return (
    <Stack spacing={2}>
      {factors.security_keys.map((key) => (
        <Button
          key={key.public_id}
          variant="outlined"
          color="error"
          aria-disabled={last || removeKey.isPending}
          onClick={() => !last && removeKey.mutate(key.public_id)}
        >
          Remove the key {key.name}
        </Button>
      ))}
      {factors.totp && (
        <Button variant="outlined" color="error" aria-disabled={last || removeTotp.isPending} onClick={() => !last && removeTotp.mutate()}>
          Remove the authenticator app
        </Button>
      )}
      {last && <Typography variant="body2">Your last second factor stays. Add another one before removing it.</Typography>}
      <Button
        variant="outlined"
        aria-disabled={newCodes.isPending}
        onClick={() => !newCodes.isPending && newCodes.mutate(undefined, { onSuccess: (r) => onCodes(r.recovery_codes) })}
      >
        New recovery codes
      </Button>
      {failure && <Alert severity="error">{factorError(failure)}</Alert>}
      <Typography component="h2" variant="h6">
        Add a second factor
      </Typography>
      <EnrolForm intro={false} onEnrolled={() => undefined} onRestart={() => undefined} />
    </Stack>
  )
}
