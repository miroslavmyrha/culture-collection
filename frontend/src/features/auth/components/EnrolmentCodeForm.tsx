import { type SubmitEvent, useState } from 'react'
import { Alert, Button, Stack, TextField, Typography } from '@/components/ui'
import { useEnrolmentCode } from '../api/factors'
import { factorError, stepExpired } from './factorErrors'

type Props = { onAccepted: () => void; onRestart: () => void }

/**
 * Before the first second factor (#176): the one-time code a manager of the lab issued. The
 * password alone enrols nothing.
 */
export function EnrolmentCodeForm({ onAccepted, onRestart }: Props) {
  const check = useEnrolmentCode()
  const [code, setCode] = useState('')
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!check.isPending) check.mutate(code, { onSuccess: onAccepted, onError: (error) => stepExpired(error) && onRestart() })
  }
  return (
    <form onSubmit={submit} noValidate aria-label="Enrolment code">
      <Stack spacing={2}>
        <Typography component="h2" variant="h6">
          Add a second factor
        </Typography>
        <Typography>Every account signs in with a second factor. Enter the enrolment code a manager of your lab gave you, then add your security key or app.</Typography>
        <TextField label="Enrolment code" autoComplete="off" value={code} onChange={(event) => setCode(event.target.value)} />
        <Button type="submit" variant="contained" aria-disabled={check.isPending}>
          Continue
        </Button>
        {check.error && <Alert severity="error">{factorError(check.error)}</Alert>}
      </Stack>
    </form>
  )
}
