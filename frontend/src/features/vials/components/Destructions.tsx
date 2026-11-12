import { type MouseEvent, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Stack, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useDestructions } from '../api/queries'
import { type Destruction, destructionRules } from '../schemas'
import { ConfirmDestructionDialog, DestructionErrorDialog, RecordDestructionDialog } from './DestructionDialogs'
import { DestructionTable, type Rights } from './DestructionRecords'

type Props = {
  labId: string
  strainId: string
  accession: string
  /** The strain's active restriction kinds, undefined until the strain loaded: nothing is recorded before. */
  kinds: readonly string[] | undefined
  canHandle: boolean
  canConfirm: boolean
}

type Common = { labId: string; strainId: string; onClose: () => void; onExited: () => void }
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

/** The records, or what stands in their place: the wait, the load error, or none yet. */
function RecordsBody({ records, rights, actions }: { records: ReturnType<typeof useDestructions>; rights: Rights; actions: Parameters<typeof DestructionTable>[0]['actions'] }) {
  if (records.data === undefined) {
    if (records.isPending) return <Typography>Loading the destructions…</Typography>
    return <LoadError what="the destructions" error={records.error} onRetry={() => void records.refetch()} />
  }
  if (records.data.count === 0) return <Typography>No destruction recorded.</Typography>
  return <DestructionTable records={records.data.results} rights={rights} actions={actions} />
}

/** The dialog the person opened, if any. Mounted until it has faded out, so onExited can place the focus. */
function DestructionDialogHost({ open, kinds, accession, waiting, common }: { open: Open; kinds: readonly string[] | undefined; accession: string; waiting: ReadonlySet<string>; common: Common }) {
  if (open === null) return null
  if (open.kind === 'record') return kinds === undefined ? null : <RecordDestructionDialog {...common} rules={destructionRules(kinds)} waiting={waiting} open={open.open} />
  if (open.kind === 'confirm') return <ConfirmDestructionDialog {...common} record={open.record} accession={accession} open={open.open} />
  return <DestructionErrorDialog {...common} record={open.record} accession={accession} open={open.open} />
}

/** The vials in a record that waits for its confirmation: no second record takes them. */
const waitingVials = (rows: readonly Destruction[] | undefined) => new Set((rows ?? []).filter((d) => d.awaits_confirmation).flatMap((d) => d.vials.map((v) => v.public_id)))

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
  const actions = {
    onConfirm: (record: Destruction) => show({ kind: 'confirm', record, open: true }),
    onError: (record: Destruction) => show({ kind: 'error', record, open: true }),
  }
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
      <RecordsBody records={records} rights={{ canHandle, canConfirm }} actions={actions} />
      <DestructionDialogHost open={open} kinds={kinds} accession={accession} waiting={waitingVials(records.data?.results)} common={common} />
    </Stack>
  )
}
