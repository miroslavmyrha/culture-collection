import { Box, Link, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { UNIT_TONES } from '@/lib/tones'
import { KIND_LABELS, STATUS_LABELS, type Unit } from '../schemas'

type Props = { labId: string; unit: Unit }

/** What the unit holds: its children in a table, or that it holds nothing yet. */
export function UnitHolds({ labId, unit: u }: Props) {
  return (
    <Box component="section" aria-label="Holds" sx={{ mt: 4 }}>
      {/* tabIndex -1: where focus goes when the control that had it is gone. */}
      <Typography component="h2" variant="h6" tabIndex={-1} gutterBottom>
        Holds
      </Typography>
      {u.children.length === 0 ? <Typography>Nothing yet.</Typography> : <HoldsTable labId={labId} unit={u} />}
    </Box>
  )
}

function HoldsTable({ labId, unit: u }: Props) {
  // A boxes column only where something held is no box: a box holds no box.
  const boxesColumn = u.children.some((c) => c.kind !== 'box')
  // A table that may scroll sideways and holds links only: a named, focusable region, so
  // the arrow keys can scroll it (WCAG 2.1.1).
  return (
    <TableContainer
      component="section"
      tabIndex={0}
      aria-label="Holds table"
      sx={{ border: 1, borderColor: 'divider', borderRadius: 1, '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 } }}
    >
      <Table aria-label={`What ${u.name} holds`}>
        <TableHead>
          <TableRow>
            <TableCell>Slot</TableCell>
            <TableCell>Name</TableCell>
            <TableCell>Kind</TableCell>
            <TableCell>Size</TableCell>
            {boxesColumn && <TableCell align="right">Boxes</TableCell>}
            <TableCell align="right">Vials</TableCell>
            <TableCell align="right">Free positions</TableCell>
            <TableCell>Status</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {u.children.map((c) => (
            <HeldRow key={c.public_id} labId={labId} held={c} boxesColumn={boxesColumn} />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

function boxesCount(c: Unit['children'][number]): number | string {
  return c.kind === 'box' ? '' : c.counts.boxes
}

function sizeCell(c: Unit['children'][number]): string {
  return c.rows !== null && c.cols !== null ? `${c.rows} x ${c.cols}` : ''
}

function HeldRow({ labId, held: c, boxesColumn }: { labId: string; held: Unit['children'][number]; boxesColumn: boolean }) {
  return (
    <TableRow>
      <TableCell>{c.slot ?? ''}</TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        <Link to="/labs/$labId/storage/$unitId" params={{ labId, unitId: c.public_id }}>
          {c.name}
        </Link>
      </TableCell>
      <TableCell>{KIND_LABELS[c.kind]}</TableCell>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>{sizeCell(c)}</TableCell>
      {boxesColumn && <TableCell align="right">{boxesCount(c)}</TableCell>}
      <TableCell align="right">{c.counts.vials}</TableCell>
      <TableCell align="right">{c.counts.free_positions}</TableCell>
      <TableCell>
        <StatusChip tone={UNIT_TONES[c.status]}>{STATUS_LABELS[c.status]}</StatusChip>
      </TableCell>
    </TableRow>
  )
}
