import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { PERMIT_TONES } from '@/lib/tones'
import { usePermitList } from '../api/queries'
import { type Permit, STANDING_LABELS, standingDetail } from '../schemas'

/**
 * The lab's permits as staff recorded them, read only. The server sorts them: what expires soon
 * first, then what holds, then what is not valid yet, then the expired and ended ones, the most
 * recent first. Expired and ended rows keep their place in the history and say so in words.
 */
export function PermitList({ labId }: { labId: string }) {
  const list = usePermitList(labId)
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the permits…</Typography>
    return <LoadError what="the permits" error={list.error} onRetry={() => void list.refetch()} />
  }
  const stale = <StaleNotice what="the permits" query={list} />
  if (list.data.length === 0)
    return (
      <>
        {stale}
        <Typography>The lab has no permit on record.</Typography>
      </>
    )
  const soon = list.data.filter((p) => p.standing === 'expires_soon').length
  return (
    <>
      {stale}
      <Typography sx={{ mb: 2 }}>{soon === 0 ? 'No permit expires soon.' : `${soon} ${soon === 1 ? 'permit expires' : 'permits expire'} soon.`}</Typography>
      {/* It may scroll sideways on a narrow screen: a named region and a tab stop, so a keyboard
          can scroll it although no cell holds a control (WCAG 2.1.1). */}
      <TableContainer
        component="section"
        tabIndex={0}
        aria-label="Permits table"
        sx={{ border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.paper', '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 } }}
      >
        <Table aria-label="Permits">
          <TableHead>
            <TableRow>
              <TableCell>Permit</TableCell>
              <TableCell>Issuer and reference</TableCell>
              <TableCell>Valid from</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {list.data.map((p) => (
              <PermitRow key={p.public_id} permit={p} />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </>
  )
}

function PermitRow({ permit: p }: { permit: Permit }) {
  const past = p.standing === 'expired' || p.standing === 'ended'
  return (
    <TableRow sx={past ? { '& td': { color: 'text.secondary' } } : undefined}>
      <TableCell sx={{ overflowWrap: 'break-word' }}>{p.kind_label}</TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        {p.issuer_label} {p.permit_reference}
      </TableCell>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>{p.valid_from}</TableCell>
      <TableCell>
        <StatusChip tone={PERMIT_TONES[p.standing]}>{STANDING_LABELS[p.standing]}</StatusChip>
        <Box component="span" sx={{ display: 'block', mt: 0.5, overflowWrap: 'break-word' }}>
          {standingDetail(p)}
        </Box>
      </TableCell>
    </TableRow>
  )
}
