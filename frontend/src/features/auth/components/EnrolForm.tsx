import { type SubmitEvent, useState } from 'react'
import { Alert, Button, Mono, Stack, TextField, Typography } from '@/components/ui'
import { type Enrolled, useKeyEnrol, useTotpEnrol, useTotpSetup } from '../api/factors'
import { factorError, stepExpired } from '../factorErrors'
import { QrCode } from './QrCode'

type Props = { onEnrolled: (result: Enrolled) => void; onRestart: () => void; intro?: boolean }

/**
 * Adds a second factor (#176): a security key first, an authenticator app as the fallback. At
 * the first sign-in after #176 this is the only page an account without a factor reaches.
 */
export function EnrolForm({ onEnrolled, onRestart, intro = true }: Props) {
  const [name, setName] = useState('')
  const [app, setApp] = useState(false)
  const key = useKeyEnrol()
  const after = { onSuccess: onEnrolled, onError: (error: unknown) => stepExpired(error) && onRestart() }
  return (
    <Stack spacing={2}>
      {intro && <Typography>Add a security key, or an authenticator app on your phone.</Typography>}
      <TextField label="Name of the key (optional)" value={name} onChange={(event) => setName(event.target.value)} />
      <Button variant="contained" aria-disabled={key.isPending} onClick={() => !key.isPending && key.mutate(name, after)}>
        Add a security key
      </Button>
      {key.error && <Alert severity="error">{factorError(key.error)}</Alert>}
      {app ? (
        <AppSetup onEnrolled={onEnrolled} onRestart={onRestart} />
      ) : (
        <Button variant="text" onClick={() => setApp(true)}>
          Use an authenticator app instead
        </Button>
      )}
    </Stack>
  )
}

function AppSetup({ onEnrolled, onRestart }: Omit<Props, 'intro'>) {
  const setup = useTotpSetup()
  const enrol = useTotpEnrol()
  const [code, setCode] = useState('')
  const after = { onSuccess: onEnrolled, onError: (error: unknown) => stepExpired(error) && onRestart() }
  if (!setup.data) {
    return (
      <Stack spacing={1}>
        <Button variant="outlined" aria-disabled={setup.isPending} onClick={() => !setup.isPending && setup.mutate(undefined, { onError: after.onError })}>
          Show the code for the app
        </Button>
        {setup.error && <Alert severity="error">{factorError(setup.error)}</Alert>}
      </Stack>
    )
  }
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!enrol.isPending) enrol.mutate(code, after)
  }
  return (
    <form onSubmit={submit} noValidate aria-label="Authenticator app">
      <Stack spacing={2}>
        <Typography>Scan this with the app, or type the key into it. Then enter the code the app shows.</Typography>
        <QrCode value={setup.data.uri} label="QR code for the authenticator app" />
        <Typography>
          Key: <Mono>{setup.data.secret}</Mono>
        </Typography>
        <TextField label="Code from the app" autoComplete="one-time-code" inputMode="numeric" value={code} onChange={(event) => setCode(event.target.value)} />
        <Button type="submit" variant="contained" aria-disabled={enrol.isPending}>
          Add the app
        </Button>
        {enrol.error && <Alert severity="error">{factorError(enrol.error)}</Alert>}
      </Stack>
    </form>
  )
}
