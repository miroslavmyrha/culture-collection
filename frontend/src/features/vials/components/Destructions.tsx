import { type MouseEvent, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useDestructions } from '../api/queries'
import { type Destruction, DESTRUCTION_METHOD_LABELS, destructionRules, destructionState } from '../schemas'
import { ConfirmDestructionDialog, DestructionErrorDialog, RecordDestructionDialog } from './DestructionDialogs'
import { scrollable } from './scroll'

type Props = {
  labId: string
  strainId: string
  accession: string
  /** The strain's active restriction kinds, undefined until the strain loaded: nothing is recorded before. */
  kinds: readonly string[] | undefined
  canHandle: boolean
  canConfirm: boolean
}

type Open = { kind: 'record'; open: boolean } | { kind: 'confirm' | 'error'; record: Destruction; open: boolean } | null

/** What a record of this strain asks, in words, from its rules. */
function rulesText(kinds: readonly string[]): string {
  const rules = destructionRules(kinds)
  if (!rules.confirmation) return 'Its strain has no active restriction: the vials are destroyed and leave their boxes when the destruction is recorded.'
  const parts = [
    'Its strain is regulated: the record says how the inactivation was verified, and a manager other than the one who recorded it confirms it. The vials are destroyed then.',
  ]
  if (rules.witness) parts.push("A highly risky agent (VRAT) names the member who witnessed the destruction, from the lab's VRAT access list.")
  if (rules.inactivatedBeforeHandover) parts.push('A highly risky or risky agent (VRAT, RAT) goes to an outside firm only inactivated in the lab.')
  if (rules.declaredMethod) parts.push("A quarantine pest is destroyed by the method the lab's ÚKZÚZ permit declares.")
  return parts.join(' ')
}

/**
 * The strain's destructions (#160): the only way a vial becomes destroyed. Technicians and up
 * record one for vials marked to destroy; a regulated strain's record waits for a manager other
 * than the recorder (ADR 0009). Every record stays, a wrong one entered in error with a reason.
 */
export function Destructions({ labId, strainId, accession, kinds, canHandle, canConfirm }: Props) {
  const records = useDestructions(labId, strainId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  // The control may be gone once the action ran (Confirm on a confirmed record): rememberFocus
  // then finds the next one in the table, or the section's heading.
  const show = (next: NonNullable<Open>) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen(next)
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }
  const common = { labId, strainId, onClose: close, onExited: exited }
  const rows = records.data?.results
  const waiting = new Set((rows ?? []).filter((d) => d.awaits_confirmation).flatMap((d) => d.vials.map((v) => v.public_id)))
  return (
    <Stack spacing={2}>
      <Typography>
        A vial marked to destroy is destroyed with a record of the destruction. {kinds !== undefined && rulesText(kinds)}
      </Typography>
      {canHandle && kinds !== undefined && (
        <Box>
          <Button variant="outlined" onClick={show({ kind: 'record', open: true })}>
            Record a destruction
          </Button>
        </Box>
      )}
      <StaleNotice what="the destructions" query={records} />
      {records.data === undefined ? (
        records.isPending ? (
          <Typography>Loading the destructions…</Typography>
        ) : (
          <LoadError what="the destructions" error={records.error} onRetry={() => void records.refetch()} />
        )
      ) : records.data.count === 0 ? (
        <Typography>No destruction recorded.</Typography>
      ) : (
        <TableContainer {...scrollable('Destruction records')}>
          <Table aria-label="Destruction records" size="small">
            <TableHead>
              <TableRow>
                <TableCell>Record</TableCell>
                <TableCell>Destroyed on</TableCell>
                <TableCell>Method</TableCell>
                <TableCell>Vials</TableCell>
                <TableCell>State</TableCell>
                {(canHandle || canConfirm) && <TableCell>Actions</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {records.data.results.map((d) => (
                <TableRow key={d.public_id}>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>{d.number}</TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>{d.destroyed_on}</TableCell>
                  <TableCell sx={{ minWidth: 160 }}>
                    {DESTRUCTION_METHOD_LABELS[d.method]}
                    {d.method_detail && `, ${d.method_detail}`}
                    {d.contractor && (
                      <Typography component="span" variant="body2" color="text.secondary" sx={{ display: 'block' }}>
                        Handed to {d.contractor}, document {d.handover_document}
                        {d.inactivated_in_lab ? ', inactivated in the lab first' : ''}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell sx={{ minWidth: 160 }}>{d.vials.map((v) => v.label).join(', ')}</TableCell>
                  <TableCell sx={{ minWidth: 200 }}>
                    {destructionState(d)}
                    {d.witness && (
                      <Typography component="span" variant="body2" color="text.secondary" sx={{ display: 'block' }}>
                        Witness: {d.witness}
                      </Typography>
                    )}
                  </TableCell>
                  {(canHandle || canConfirm) && (
                    <TableCell>
                      <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
                        {canConfirm && d.awaits_confirmation && (
                          <Button size="small" variant="outlined" aria-label={`Confirm destruction ${d.number}`} onClick={show({ kind: 'confirm', record: d, open: true })}>
                            Confirm
                          </Button>
                        )}
                        {d.status === 'valid' && canHandle && (d.confirmed_by === null || canConfirm) && (
                          <Button size="small" aria-label={`Enter destruction ${d.number} in error`} onClick={show({ kind: 'error', record: d, open: true })}>
                            Enter in error
                          </Button>
                        )}
                      </Stack>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {/* Mounted until they have faded out, so onExited can place the focus. */}
      {open?.kind === 'record' && kinds !== undefined && <RecordDestructionDialog {...common} rules={destructionRules(kinds)} waiting={waiting} open={open.open} />}
      {open?.kind === 'confirm' && <ConfirmDestructionDialog {...common} record={open.record} accession={accession} open={open.open} />}
      {open?.kind === 'error' && <DestructionErrorDialog {...common} record={open.record} accession={accession} open={open.open} />}
    </Stack>
  )
}
