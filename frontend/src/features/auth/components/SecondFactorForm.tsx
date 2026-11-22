import { type SubmitEvent, useState } from 'react'
import { Alert, Button, Stack, TextField, Typography } from '@/components/ui'
import { type Me, type Method, useCodeSignIn, useKeySignIn } from '../api/factors'
import { factorError, stepExpired } from './factorErrors'

type Props = { methods: Method[]; onSignedIn: (me: Me) => void; onRestart: () => void }

/**
 * The second step of the sign-in (#176): the security key first, the authenticator app as the
 * fallback, a recovery code when both are lost. Also the step-up of a signed-in user.
 */
export function SecondFactorForm({ methods, onSignedIn, onRestart }: Props) {
  const key = useKeySignIn()
  const code = useCodeSignIn()
  const [method, setMethod] = useState<'totp' | 'recovery_code'>(methods.includes('totp') ? 'totp' : 'recovery_code')
  const [value, setValue] = useState('')
  const failure = key.error ?? code.error
  const after = { onSuccess: onSignedIn, onError: (error: unknown) => stepExpired(error) && onRestart() }
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (code.isPending) return
    code.mutate({ method, code: value }, after)
  }
  const fallback = method === 'totp' && methods.includes('recovery_code')
  return (
    <Stack spacing={2}>
      <Typography component="h2" variant="h6">
        Confirm it is you
      </Typography>
      {methods.includes('security_key') && (
        <Button variant="contained" aria-disabled={key.isPending} onClick={() => !key.isPending && key.mutate(undefined, after)}>
          Use your security key
        </Button>
      )}
      {(methods.includes('totp') || methods.includes('recovery_code')) && (
        <CodeForm method={method} value={value} onChange={setValue} onSubmit={submit} primary={!methods.includes('security_key')} pending={code.isPending} />
      )}
      {fallback && (
        <Button variant="text" onClick={() => setMethod('recovery_code')}>
          Use a recovery code instead
        </Button>
      )}
      {failure && <Alert severity="error">{factorError(failure)}</Alert>}
    </Stack>
  )
}

type CodeProps = {
  method: 'totp' | 'recovery_code'
  value: string
  onChange: (value: string) => void
  onSubmit: (event: SubmitEvent<HTMLFormElement>) => void
  primary: boolean
  pending: boolean
}

/** A code from the authenticator app, or a recovery code. */
function CodeForm({ method, value, onChange, onSubmit, primary, pending }: CodeProps) {
  const totp = method === 'totp'
  return (
    <form onSubmit={onSubmit} noValidate aria-label="Code">
      <Stack spacing={2}>
        <TextField
          label={totp ? 'Code from your authenticator app' : 'Recovery code'}
          autoComplete="one-time-code"
          inputMode={totp ? 'numeric' : 'text'}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        <Button type="submit" variant={primary ? 'contained' : 'outlined'} aria-disabled={pending}>
          Continue
        </Button>
      </Stack>
    </form>
  )
}
