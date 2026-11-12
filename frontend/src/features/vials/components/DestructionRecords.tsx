import type { MouseEvent } from 'react'
import { Button, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { type Destruction, DESTRUCTION_METHOD_LABELS, destructionState } from '../schemas'
import { scrollable } from './scroll'

/** What a person may do with the records: record and enter in error (technicians and up), confirm (managers). */
export type Rights = { canHandle: boolean; canConfirm: boolean }

/** A note under a cell, smaller and quieter than the cell's own text. */
function Note({ children }: { children: string }) {
  return (
    <Typography component="span" variant="body2" color="text.secondary" sx={{ display: 'block' }}>
      {children}
    </Typography>
  )
}

/** The method, its details, and for a firm that took the vials who, with which document. */
function MethodCell({ record: d }: { record: Destruction }) {
  const handover = `Handed to ${d.contractor}, document ${d.handover_document}${d.inactivated_in_lab ? ', inactivated in the lab first' : ''}`
  return (
    <TableCell sx={{ minWidth: 160 }}>
      {DESTRUCTION_METHOD_LABELS[d.method]}
      {d.method_detail && `, ${d.method_detail}`}
      {d.contractor && <Note>{handover}</Note>}
    </TableCell>
  )
}

/** Where the record stands, and for a VRAT who witnessed it. */
function StateCell({ record: d }: { record: Destruction }) {
  return (
    <TableCell sx={{ minWidth: 200 }}>
      {destructionState(d)}
      {d.witness && <Note>{`Witness: ${d.witness}`}</Note>}
    </TableCell>
  )
}

type Actions = { onConfirm: (record: Destruction) => (event: MouseEvent<HTMLButtonElement>) => void; onError: (record: Destruction) => (event: MouseEvent<HTMLButtonElement>) => void }

/** A record waiting for its confirmation is confirmed by a manager. */
const mayConfirm = (d: Destruction, rights: Rights) => rights.canConfirm && d.awaits_confirmation

/** A valid record is entered in error by a technician or up; one a manager confirmed, by a manager. */
const mayEnterInError = (d: Destruction, rights: Rights) => d.status === 'valid' && rights.canHandle && (d.confirmed_by === null || rights.canConfirm)

function ActionsCell({ record: d, rights, actions }: { record: Destruction; rights: Rights; actions: Actions }) {
  return (
    <TableCell>
      <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
        {mayConfirm(d, rights) && (
          <Button size="small" variant="outlined" aria-label={`Confirm destruction ${d.number}`} onClick={actions.onConfirm(d)}>
            Confirm
          </Button>
        )}
        {mayEnterInError(d, rights) && (
          <Button size="small" aria-label={`Enter destruction ${d.number} in error`} onClick={actions.onError(d)}>
            Enter in error
          </Button>
        )}
      </Stack>
    </TableCell>
  )
}

function RecordRow({ record: d, rights, actions }: { record: Destruction; rights: Rights; actions: Actions }) {
  return (
    <TableRow>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>{d.number}</TableCell>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>{d.destroyed_on}</TableCell>
      <MethodCell record={d} />
      <TableCell sx={{ minWidth: 160 }}>{d.vials.map((v) => v.label).join(', ')}</TableCell>
      <StateCell record={d} />
      {(rights.canHandle || rights.canConfirm) && <ActionsCell record={d} rights={rights} actions={actions} />}
    </TableRow>
  )
}

/** Every destruction record of the strain, with the actions the person may take on each. */
export function DestructionTable({ records, rights, actions }: { records: readonly Destruction[]; rights: Rights; actions: Actions }) {
  return (
    <TableContainer {...scrollable('Destruction records')}>
      <Table aria-label="Destruction records" size="small">
        <TableHead>
          <TableRow>
            <TableCell>Record</TableCell>
            <TableCell>Destroyed on</TableCell>
            <TableCell>Method</TableCell>
            <TableCell>Vials</TableCell>
            <TableCell>State</TableCell>
            {(rights.canHandle || rights.canConfirm) && <TableCell>Actions</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {records.map((d) => (
            <RecordRow key={d.public_id} record={d} rights={rights} actions={actions} />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
