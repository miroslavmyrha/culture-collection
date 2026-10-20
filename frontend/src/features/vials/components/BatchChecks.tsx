import type { MouseEvent } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Stack, Typography } from '@/components/ui'
import { useBatchChecks } from '../api/queries'
import {
  BATCH_STATUS_LABELS,
  type Batch,
  type BatchCheck,
  batchStatusReason,
  CHECK_KINDS,
  checkDetails,
  KIND_LABELS,
  mayHold,
  mayRelease,
  RESULT_LABELS,
} from '../schemas'

type Click = MouseEvent<HTMLButtonElement>

type Props = {
  labId: string
  strainId: string
  batch: Batch
  /** The id of the panel's heading: focus goes there when the control that had it is gone. */
  headingId: string
  canHandle: boolean
  canRelease: boolean
  onRecord: (event: Click, checks: readonly BatchCheck[] | undefined) => void
  onDecide: (event: Click, decision: 'release' | 'hold') => void
  onEnterInError: (event: Click, check: BatchCheck) => void
}

/**
 * One batch's checks (ADR 0008, D16), shown when its row is opened: the status and why, the
 * latest result of each kind, the bench and curator actions, and the history, newest first,
 * with the checks entered in error marked. The history loads only when the panel opens.
 */
export function BatchChecks({ labId, strainId, batch, headingId, canHandle, canRelease, onRecord, onDecide, onEnterInError }: Props) {
  const checks = useBatchChecks(labId, strainId, batch.public_id)
  const rows = checks.data?.results
  const record = canHandle && batch.status !== 'exhausted'
  const release = canRelease && mayRelease(batch)
  const hold = canRelease && mayHold(batch)
  return (
    <Stack spacing={1.5}>
      <Typography component="h3" variant="subtitle1" id={headingId} tabIndex={-1} sx={{ fontWeight: 600 }}>
        Batch {batch.number}: {BATCH_STATUS_LABELS[batch.status]}
      </Typography>
      {batchStatusReason(batch) && <Typography variant="body2">{batchStatusReason(batch)}</Typography>}
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
      {(record || release || hold) && (
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
          {record && (
            <Button size="small" variant="outlined" onClick={(event) => onRecord(event, rows)}>
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
      )}
      <Typography component="h4" variant="subtitle2">
        History
      </Typography>
      <StaleNotice what="the checks" query={checks} />
      {checks.isPending ? (
        <Typography variant="body2">Loading the checks…</Typography>
      ) : rows === undefined ? (
        <LoadError what="the checks" error={checks.error} onRetry={() => void checks.refetch()} />
      ) : rows.length === 0 ? (
        <Typography variant="body2">No check recorded yet.</Typography>
      ) : (
        <Box component="ol" aria-label={`Checks of batch ${batch.number}`} sx={{ m: 0, p: 0, listStyle: 'none' }}>
          {rows.map((check) => (
            <Box component="li" key={check.public_id} sx={{ py: 0.75, borderTop: 1, borderColor: 'divider' }}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {check.checked_on}, {KIND_LABELS[check.kind]}, {RESULT_LABELS[check.result]}
                {check.status === 'entered_in_error' && ', entered in error'}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {checkDetails(check)}
              </Typography>
              {check.note && <Typography variant="body2">{check.note}</Typography>}
              {check.status === 'entered_in_error' && <Typography variant="body2">Why it was entered in error: {check.reason}</Typography>}
              {canHandle && check.status === 'valid' && (
                <Button
                  size="small"
                  aria-label={`Enter the ${KIND_LABELS[check.kind].toLowerCase()} check of ${check.checked_on} in error`}
                  onClick={(event) => onEnterInError(event, check)}
                >
                  Enter in error
                </Button>
              )}
            </Box>
          ))}
        </Box>
      )}
    </Stack>
  )
}
