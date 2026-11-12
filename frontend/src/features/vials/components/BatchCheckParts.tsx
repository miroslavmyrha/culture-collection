import type { MouseEvent } from 'react'
import { LoadError } from '@/components/LoadError'
import { Box, Button, Stack, Typography } from '@/components/ui'
import type { useBatchChecks } from '../api/queries'
import { BATCH_STATUS_LABELS, type Batch, type BatchCheck, batchStatusReason, CHECK_KINDS, checkDetails, KIND_LABELS, RESULT_LABELS } from '../schemas'

type Click = MouseEvent<HTMLButtonElement>

/** The batch's number and state, and the reason the state has, when it has one. The heading is where focus goes when the control that had it is gone. */
export function BatchHeading({ batch, headingId }: { batch: Batch; headingId: string }) {
  const reason = batchStatusReason(batch)
  return (
    <>
      <Typography component="h3" variant="subtitle1" id={headingId} tabIndex={-1} sx={{ fontWeight: 600 }}>
        Batch {batch.number}: {BATCH_STATUS_LABELS[batch.status]}
      </Typography>
      {reason && <Typography variant="body2">{reason}</Typography>}
    </>
  )
}

/** The latest result of each kind of check. */
export function LatestChecks({ batch }: { batch: Batch }) {
  return (
    <Box component="ul" aria-label={`Latest checks of batch ${batch.number}`} sx={{ m: 0, pl: 2.5 }}>
      {CHECK_KINDS.map((kind) => {
        const result = batch.latest_checks[kind]
        return (
          <Typography component="li" variant="body2" key={kind}>
            {KIND_LABELS[kind]}: {result ? RESULT_LABELS[result] : 'not checked yet'}
          </Typography>
        )
      })}
    </Box>
  )
}

type ActionsProps = { record: boolean; release: boolean; hold: boolean; onDecide: (event: Click, decision: 'release' | 'hold') => void; onRecordClick: (event: Click) => void }

/** The bench and curator actions the person may take on the batch, none at all when there are none. */
export function BatchActions({ record, release, hold, onRecordClick, onDecide }: ActionsProps) {
  if (!(record || release || hold)) return null
  return (
    <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
      {record && (
        <Button size="small" variant="outlined" onClick={onRecordClick}>
          Record a check
        </Button>
      )}
      {release && (
        <Button size="small" variant="outlined" onClick={(event) => onDecide(event, 'release')}>
          Release
        </Button>
      )}
      {hold && (
        <Button size="small" variant="outlined" onClick={(event) => onDecide(event, 'hold')}>
          Hold
        </Button>
      )}
    </Stack>
  )
}

const isWrong = (check: BatchCheck) => check.status === 'entered_in_error'

/** One check of the history: what, when and the result, its details and note, and for a wrong one why. */
function CheckItem({ check, canEnterInError, onEnterInError }: { check: BatchCheck; canEnterInError: boolean; onEnterInError: (event: Click, check: BatchCheck) => void }) {
  return (
    <Box component="li" sx={{ py: 0.75, borderTop: 1, borderColor: 'divider' }}>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {check.checked_on}, {KIND_LABELS[check.kind]}, {RESULT_LABELS[check.result]}
        {isWrong(check) && ', entered in error'}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {checkDetails(check)}
      </Typography>
      {check.note && <Typography variant="body2">{check.note}</Typography>}
      {isWrong(check) && <Typography variant="body2">Why it was entered in error: {check.reason}</Typography>}
      {canEnterInError && check.status === 'valid' && (
        <Button size="small" aria-label={`Enter the ${KIND_LABELS[check.kind].toLowerCase()} check of ${check.checked_on} in error`} onClick={(event) => onEnterInError(event, check)}>
          Enter in error
        </Button>
      )}
    </Box>
  )
}

type HistoryProps = {
  checks: ReturnType<typeof useBatchChecks>
  batch: Batch
  canEnterInError: boolean
  onEnterInError: (event: Click, check: BatchCheck) => void
}

/** The history, newest first, or what stands in its place: the wait, the load error, or none yet. */
export function CheckHistory({ checks, batch, canEnterInError, onEnterInError }: HistoryProps) {
  const rows = checks.data?.results
  if (checks.isPending) return <Typography variant="body2">Loading the checks…</Typography>
  if (rows === undefined) return <LoadError what="the checks" error={checks.error} onRetry={() => void checks.refetch()} />
  if (rows.length === 0) return <Typography variant="body2">No check recorded yet.</Typography>
  return (
    <Box component="ol" aria-label={`Checks of batch ${batch.number}`} sx={{ m: 0, p: 0, listStyle: 'none' }}>
      {rows.map((check) => (
        <CheckItem key={check.public_id} check={check} canEnterInError={canEnterInError} onEnterInError={onEnterInError} />
      ))}
    </Box>
  )
}
