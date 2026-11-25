import { type SubmitEvent, useId, useState } from 'react'
import { Alert, Box, Button, Mono, Stack, TextField, Typography } from '@/components/ui'
import { resetError } from '../resetErrors'
import { type FactorReset, useDecideReset, useFactorResets, useProposeReset } from '../api/factorResets'
import { useMemberList } from '../api/queries'

const ALL_MEMBERS = { limit: 200, offset: 0 }

type Handover = { username: string; code: string }


/**
 * For managers, on the lab page (#176): a member who lost every second factor and every
 * recovery code gets them reset by two managers, one proposes and another confirms, never the
 * member. They then add a new factor at their next sign-in.
 */
export function FactorResets({ labId }: { labId: string }) {
  const headingId = useId()
  const resets = useFactorResets(labId)
  // The confirmed reset leaves the list: its code is kept here, shown this once.
  const [handover, setHandover] = useState<Handover | null>(null)
  return (
    <Box component="section" aria-labelledby={headingId} sx={{ mt: 5 }}>
      <Typography component="h2" variant="h6" id={headingId} gutterBottom>
        Second factor resets
      </Typography>
      <Typography sx={{ mb: 2 }}>
        When a member lost their security key, their authenticator app and their recovery codes, one manager proposes a reset and another confirms it. The member then signs in with their
        password and adds a new second factor.
      </Typography>
      {handover && (
        // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- MUI Alert owns its root element; role="status" is what <output> would give
        <Alert severity="success" role="status" sx={{ mb: 2 }}>
          Reset done. Hand {handover.username} this enrolment code in person, it is not shown again: <Mono>{handover.code}</Mono>
        </Alert>
      )}
      {resets.data?.length === 0 && <Typography sx={{ mb: 2 }}>No reset waits.</Typography>}
      <Stack spacing={2} sx={{ mb: 3 }}>
        {resets.data?.map((reset) => (
          <OpenReset key={reset.public_id} labId={labId} reset={reset} onHandover={setHandover} />
        ))}
      </Stack>
      <ProposeForm labId={labId} />
    </Box>
  )
}

function OpenReset({ labId, reset, onHandover }: { labId: string; reset: FactorReset; onHandover: (h: Handover) => void }) {
  const [reason, setReason] = useState('')
  const confirm = useDecideReset(labId, 'confirm')
  const withdraw = useDecideReset(labId, 'withdraw')
  const failure = confirm.error ?? withdraw.error
  const decide = (action: typeof confirm) => {
    if (action.isPending) return
    action.mutate({ publicId: reset.public_id, reason }, { onSuccess: (done) => done.enrolment_code && onHandover({ username: done.username, code: done.enrolment_code }) })
  }
  return (
    <Box component="article" aria-label={`Reset for ${reset.username}`} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2 }}>
      <Typography>
        {reset.username}: proposed by {reset.proposed_by}. {reset.reason}
      </Typography>
      <Stack spacing={1} sx={{ mt: 1 }}>
        <TextField label={`Reason (reset for ${reset.username})`} value={reason} onChange={(event) => setReason(event.target.value)} />
        <Stack direction="row" spacing={1}>
          {reset.may_confirm && (
            <Button variant="contained" color="error" aria-disabled={confirm.isPending} onClick={() => decide(confirm)}>
              Confirm the reset
            </Button>
          )}
          <Button variant="outlined" aria-disabled={withdraw.isPending} onClick={() => decide(withdraw)}>
            Withdraw
          </Button>
        </Stack>
        {!reset.may_confirm && <Typography variant="body2">Another manager confirms it.</Typography>}

        {failure && <Alert severity="error">{resetError(failure)}</Alert>}
      </Stack>
    </Box>
  )
}

function ProposeForm({ labId }: { labId: string }) {
  const members = useMemberList(labId, ALL_MEMBERS)
  const propose = useProposeReset(labId)
  const [username, setUsername] = useState('')
  const [reason, setReason] = useState('')
  const [unknown, setUnknown] = useState(false)
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (propose.isPending) return
    const member = members.data?.results.find((m) => m.username === username.trim())
    setUnknown(member === undefined)
    if (member) propose.mutate({ member: member.public_id, reason }, { onSuccess: () => setReason('') })
  }
  return (
    <form onSubmit={submit} noValidate aria-label="Propose a second factor reset">
      <Stack spacing={2}>
        <TextField label="Username of the member" value={username} onChange={(event) => setUsername(event.target.value)} />
        <TextField label="Reason" value={reason} onChange={(event) => setReason(event.target.value)} />
        <Button type="submit" variant="outlined" aria-disabled={propose.isPending}>
          Propose a reset
        </Button>
        {unknown && <Alert severity="error">No member of this lab has that username.</Alert>}
        {propose.error && <Alert severity="error">{resetError(propose.error)}</Alert>}
      </Stack>
    </form>
  )
}
