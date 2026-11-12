import { useId, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { BATCH_TONES } from '@/lib/tones'
import type { useBatches } from '../api/queries'
import { type Batch, BATCH_STATUS_LABELS, batchStatusReason, METHOD_LABELS, PURPOSE_LABELS } from '../schemas'
import { BatchChecks } from './BatchChecks'
import { type InPanel, type Show } from './materialOpen'
import { MaterialSection } from './MaterialSection'
import { scrollable } from './scroll'

type Props = {
  labId: string
  strainId: string
  batches: ReturnType<typeof useBatches>
  /** A batch is preserved from a passage: without one there is nothing to preserve from. */
  hasPassages: boolean
  canHandle: boolean
  canRelease: boolean
  show: Show
  inPanel: InPanel
}

/** The strain's batches and what can be supplied from them; a batch's checks open in its row (D16). */
export function BatchesSection({ labId, strainId, batches, hasPassages, canHandle, canRelease, show, inPanel }: Props) {
  return (
    <MaterialSection title="Batches">
      {canHandle && hasPassages && (
        <Box>
          <Button variant="outlined" onClick={show({ kind: 'preserve', open: true })}>
            Preserve a batch
          </Button>
        </Box>
      )}
      <StaleNotice what="the batches" query={batches} />
      <BatchesBody labId={labId} strainId={strainId} batches={batches} canHandle={canHandle} canRelease={canRelease} inPanel={inPanel} />
    </MaterialSection>
  )
}

function BatchesBody({ labId, strainId, batches, canHandle, canRelease, inPanel }: Omit<Props, 'hasPassages' | 'show'>) {
  if (batches.isPending) return <Typography>Loading the batches…</Typography>
  if (batches.data === undefined) return <LoadError what="the batches" error={batches.error} onRetry={() => void batches.refetch()} />
  if (batches.data.count === 0) return <Typography>No batch preserved yet.</Typography>
  return (
    <>
      <Typography>{supply(batches.data.results)}</Typography>
      <BatchTable labId={labId} strainId={strainId} rows={batches.data.results} canHandle={canHandle} canRelease={canRelease} inPanel={inPanel} />
    </>
  )
}

type TableProps = {
  labId: string
  strainId: string
  rows: readonly Batch[]
  canHandle: boolean
  canRelease: boolean
  inPanel: InPanel
}

function BatchTable({ labId, strainId, rows, canHandle, canRelease, inPanel }: TableProps) {
  // The batches whose checks are open. A control in a panel that the action removes (Release
  // once released) gives the focus to the panel's heading.
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set())
  const toggle = (batchId: string) =>
    setOpened((current) => {
      const next = new Set(current)
      if (!next.delete(batchId)) next.add(batchId)
      return next
    })
  const panelId = useId()
  return (
    <TableContainer {...scrollable('Batches')} sx={{ ...scrollable('Batches').sx, containerType: 'inline-size' }}>
      <Table aria-label="Batches" size="small">
        <TableHead>
          <TableRow>
            <TableCell>Batch</TableCell>
            <TableCell>From passage</TableCell>
            <TableCell>Method</TableCell>
            <TableCell>Purpose</TableCell>
            <TableCell>Preserved on</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Vials available</TableCell>
            <TableCell>Checks</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((b) => (
            <BatchRow
              key={b.public_id}
              batch={b}
              panel={`${panelId}-${b.number}`}
              expanded={opened.has(b.public_id)}
              onToggle={() => toggle(b.public_id)}
              labId={labId}
              strainId={strainId}
              canHandle={canHandle}
              canRelease={canRelease}
              inPanel={inPanel}
            />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

type RowProps = {
  batch: Batch
  /** The id of the checks panel, which the row's button controls. */
  panel: string
  expanded: boolean
  onToggle: () => void
  labId: string
  strainId: string
  canHandle: boolean
  canRelease: boolean
  inPanel: InPanel
}

/** A batch's row and, when it is opened, the row under it that holds its checks. */
function BatchRow({ batch: b, panel, expanded, onToggle, labId, strainId, canHandle, canRelease, inPanel }: RowProps) {
  const heading = `${panel}-heading`
  return (
    <>
      <TableRow>
        <TableCell>{b.number}</TableCell>
        <TableCell>{b.passage_number}</TableCell>
        <TableCell>
          {METHOD_LABELS[b.method]}
          {b.cryoprotectant && `, ${b.cryoprotectant}`}
        </TableCell>
        <TableCell>{PURPOSE_LABELS[b.purpose]}</TableCell>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>{b.preserved_on}</TableCell>
        <TableCell sx={{ minWidth: 160 }}>
          <StatusChip tone={BATCH_TONES[b.status]}>{BATCH_STATUS_LABELS[b.status]}</StatusChip>
          {b.status !== 'released' && (
            <Typography component="span" variant="body2" color="text.secondary" sx={{ display: 'block' }}>
              {batchStatusReason(b)}
            </Typography>
          )}
        </TableCell>
        <TableCell>
          {b.vials_available} of {b.vial_count_created}
        </TableCell>
        <TableCell>
          <Button size="small" aria-expanded={expanded} aria-controls={panel} aria-label={`Checks of batch ${b.number}`} onClick={onToggle}>
            Checks
          </Button>
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell colSpan={8} sx={{ p: 0 }}>
            {/* As wide as the visible part of the table, and kept in view when it scrolls sideways. */}
            <Box id={panel} sx={{ position: 'sticky', left: 0, width: '100cqi', boxSizing: 'border-box', p: 2 }}>
              <BatchChecks
                labId={labId}
                strainId={strainId}
                batch={b}
                headingId={heading}
                canHandle={canHandle}
                canRelease={canRelease}
                onRecord={(event, checks) => inPanel(heading, { kind: 'check', batch: b, checks, open: true })(event)}
                onDecide={(event, decision) => inPanel(heading, { kind: decision, batch: b, open: true })(event)}
                onEnterInError={(event, check) => inPanel(heading, { kind: 'check-error', check, open: true })(event)}
              />
            </Box>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}

/** Can the collection supply the strain now: the vials of its released distribution batches. */
function supply(batches: readonly Batch[]): string {
  const ready = batches.filter((b) => b.vials_distributable > 0)
  const vials = ready.reduce((sum, b) => sum + b.vials_distributable, 0)
  if (vials === 0) return 'Available for distribution: none. No released batch of distribution stock has a vial left.'
  const from = ready.length === 1 ? `batch ${ready[0]?.number ?? ''}` : `batches ${ready.map((b) => b.number).join(', ')}`
  return `Available for distribution: ${vials} ${vials === 1 ? 'vial' : 'vials'}, from released ${from}.`
}
