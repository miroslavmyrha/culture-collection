import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Mono, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { useRequestVials } from '../api/queries'
import { scrollable } from './scroll'
import { VialPlace } from './VialPlace'

type Props = { labId: string; requestId: string }

/**
 * The vials reserved for a request and where each lies (#143), for the person who pulls them
 * for the shipment. The server sends them in the order of one walk through the storage: by the
 * path of the box (each level by slot, then name), then row and column; the vials of a
 * regulated strain after them, their place hidden as on the strain page (a spot in the walk
 * would tell it), with the reveal for a holder of the location grant; the vials in no box last.
 */
export function VialsToPull({ labId, requestId }: Props) {
  const vials = useRequestVials(labId, requestId)
  if (vials.data === undefined) {
    if (vials.isPending) return <Typography>Loading the vials to pull…</Typography>
    return <LoadError what="the vials to pull" error={vials.error} onRetry={() => void vials.refetch()} />
  }
  const hidden = vials.data.some((v) => v.location_masked)
  return (
    <>
      <StaleNotice what="the vials to pull" query={vials} />
      {vials.data.length === 0 ? (
        <Typography>No vial is reserved for this request now.</Typography>
      ) : (
        <>
          <Typography>
            In the order of one walk through the storage: freezer, rack and box, then position.
            {hidden && ' Vials of a regulated strain come after the others: their place is hidden, and a spot in the walk would tell it.'}
          </Typography>
          <TableContainer {...scrollable('Vials to pull')}>
            <Table aria-label="Vials to pull" size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Order</TableCell>
                  <TableCell>Vial</TableCell>
                  <TableCell>Location</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {vials.data.map((v, i) => (
                  <TableRow key={v.public_id}>
                    <TableCell>{i + 1}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>
                      <Mono>{v.label}</Mono>
                    </TableCell>
                    {/* A revealed place answers one request: a state change starts the cell again. */}
                    <TableCell sx={{ minWidth: 200 }}>
                      <VialPlace key={v.status_changed_at ?? ''} labId={labId} vial={v} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}
    </>
  )
}
