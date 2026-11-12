import type { MouseEvent } from 'react'
import { StaleNotice } from '@/components/StaleNotice'
import { Stack, Typography } from '@/components/ui'
import { useBatchChecks } from '../api/queries'
import { type Batch, type BatchCheck, mayHold, mayRelease } from '../schemas'
import { BatchActions, BatchHeading, CheckHistory, LatestChecks } from './BatchCheckParts'

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
  return (
    <Stack spacing={1.5}>
      <BatchHeading batch={batch} headingId={headingId} />
      <LatestChecks batch={batch} />
      <BatchActions
        record={canHandle && batch.status !== 'exhausted'}
        release={canRelease && mayRelease(batch)}
        hold={canRelease && mayHold(batch)}
        onRecordClick={(event) => onRecord(event, checks.data?.results)}
        onDecide={onDecide}
      />
      <Typography component="h4" variant="subtitle2">
        History
      </Typography>
      <StaleNotice what="the checks" query={checks} />
      <CheckHistory checks={checks} batch={batch} canEnterInError={canHandle} onEnterInError={onEnterInError} />
    </Stack>
  )
}
