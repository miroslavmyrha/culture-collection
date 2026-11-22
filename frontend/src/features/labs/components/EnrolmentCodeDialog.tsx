import { useState } from 'react'
import { ConfirmDialog, Mono, Stack, TextField, Typography } from '@/components/ui'
import { errorMessage, isApiError, readProblem } from '@/lib/api'
import { useIssueEnrolmentCode } from '../api/factorResets'
import type { Member } from '../schemas'

type Props = { labId: string; member: Member; open: boolean; onClose: () => void; onExited: () => void }

const refusal = (error: unknown) => (isApiError(error) && [400, 409, 422].includes(error.status) ? readProblem(error.body)?.detail : undefined) ?? errorMessage(error)

/**
 * A manager issues a member a one-time code for their first second factor (#176): without it a
 * password enrols nothing. The code is shown here once, to be handed over in person.
 */
export function EnrolmentCodeDialog({ member, open, onClose, onExited }: Props) {
  const issue = useIssueEnrolmentCode()
  const [reason, setReason] = useState('')
  const title = `Issue an enrolment code for ${member.username}`
  if (issue.data) {
    return (
      <ConfirmDialog open={open} title={title} description="Hand this code over in person. It is not shown again." confirmLabel="Done" pending={false} onClose={onClose} onExited={onExited} onConfirm={onClose}>
        <Stack spacing={1}>
          <Typography>
            Code: <Mono>{issue.data.code}</Mono>
          </Typography>
          <Typography variant="body2">Valid for {issue.data.valid_hours} hours, once.</Typography>
        </Stack>
      </ConfirmDialog>
    )
  }
  return (
    <ConfirmDialog
      open={open}
      title={title}
      description="They enter it after their password to add their first second factor. Valid for one sign-in, for a day."
      confirmLabel="Issue the code"
      pending={issue.isPending}
      error={issue.error ? refusal(issue.error) : undefined}
      onClose={onClose}
      onExited={onExited}
      onConfirm={() => issue.mutate({ member: member.public_id, reason })}
    >
      <TextField label="Reason" value={reason} onChange={(event) => setReason(event.target.value)} />
    </ConfirmDialog>
  )
}
