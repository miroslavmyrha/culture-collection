import { type MouseEvent, type ReactNode, useState } from 'react'
import { Alert, Box, Button, Link, Stack, Typography } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { useFocusReturnOnUnmount } from '@/lib/focus'
import { useStartCheck } from '../api/mutations'
import type { Deposit } from '../schemas'
import { day } from './DepositParts'

type Props = { deposit: Deposit; labId: string; canManage: boolean; renderAccept: (deposit: Deposit) => ReactNode; onReject: (event: MouseEvent<HTMLButtonElement>) => void }

/** What a person without the manager role is told while the intake waits on someone else. */
const WAITING_TEXT = { received: 'The check has not started.', other: 'The deposit is being checked.' }

type Strain = NonNullable<Deposit['strain']>

function Accepted({ deposit, strain, labId }: { deposit: Deposit; strain: Strain; labId: string }) {
  return (
    <Typography>
      Accepted on {day(deposit.decided_at ?? deposit.created_at)} as strain{' '}
      <Link to="/labs/$labId/strains/$strainId" params={{ labId, strainId: strain.public_id }}>
        {strain.accession_number ?? 'pending'}
      </Link>
      . The material as received is its passage 0.
    </Typography>
  )
}

function Rejected({ deposit }: { deposit: Deposit }) {
  return (
    <Typography sx={{ overflowWrap: 'anywhere' }}>
      Rejected on {day(deposit.decided_at ?? deposit.created_at)}: {deposit.rejection_reason}
    </Typography>
  )
}

/** The open check: what it found is recorded by accepting or rejecting. */
function OpenCheck({ deposit, renderAccept, onReject }: Pick<Props, 'deposit' | 'renderAccept' | 'onReject'>) {
  return (
    <KeepsFocus>
      <Typography>Record what the check found. Accepting creates the strain with its number; rejecting ends the deposit.</Typography>
      {renderAccept(deposit)}
      <Box>
        <Button color="error" variant="outlined" onClick={onReject}>
          Reject the deposit
        </Button>
      </Box>
    </KeepsFocus>
  )
}

/** The decision step: accepted, rejected, waiting for a manager, the check to start, or the check to record. */
export function Decision({ deposit, labId, canManage, renderAccept, onReject }: Props) {
  if (deposit.status === 'accepted' && deposit.strain) return <Accepted deposit={deposit} strain={deposit.strain} labId={labId} />
  if (deposit.status === 'rejected') return <Rejected deposit={deposit} />
  if (!canManage) return <Typography>{WAITING_TEXT[deposit.status === 'received' ? 'received' : 'other']}</Typography>
  if (deposit.status === 'received') return <StartCheck labId={labId} depositId={deposit.public_id} />
  return <OpenCheck deposit={deposit} renderAccept={renderAccept} onReject={onReject} />
}

/** The line under the start button for a refused start: a deposit that changed meanwhile has its own. */
function startFailure(error: unknown): string {
  return isApiError(error, 409) && error.code === 'deposit_state' ? 'The deposit changed meanwhile. Reload the page.' : errorMessage(error)
}

/** Its button goes away when the check starts: focus then moves to the section's heading. */
function StartCheck({ labId, depositId }: { labId: string; depositId: string }) {
  const start = useStartCheck(labId, depositId)
  const remember = useFocusReturnOnUnmount()
  const [failure, setFailure] = useState<string>()
  return (
    <Stack spacing={2}>
      <Typography>Start the check when the material is being tested for purity and identity.</Typography>
      <Box>
        <Button
          variant="contained"
          aria-disabled={start.isPending}
          onClick={(event) => {
            if (start.isPending) return
            remember(event.currentTarget)
            setFailure(undefined)
            start.mutate(undefined, { onError: (error) => setFailure(startFailure(error)) })
          }}
        >
          Start checking
        </Button>
      </Box>
      {failure && <Alert severity="error">{failure}</Alert>}
    </Stack>
  )
}

/**
 * The acceptance form and the reject button go away with the decision: when the focused one
 * is removed, focus moves to the section's heading, never to the body.
 */
function KeepsFocus({ children }: { children: ReactNode }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Stack spacing={2} onFocus={(event) => remember(event.target)}>
      {children}
    </Stack>
  )
}
