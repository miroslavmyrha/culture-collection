import { useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'
import { StaleNotice } from '@/components/StaleNotice'
import { Link, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { useStrainShipments } from '../api/queries'
import { countryName } from '../schemas'
import { day, scrollable, Section } from './parts'

const LIMIT = 20

/**
 * Where the strain's distributed vials went (#20): each shipment with its request, the
 * institution, the country, the day and how many vials, oldest first. For a notice to the
 * recipients when a strain that left turns out contaminated or misidentified. Names no person.
 */
export function StrainShipments({ labId, strainId }: { labId: string; strainId: string }) {
  const [offset, setOffset] = useState(0)
  const page = { limit: LIMIT, offset }
  const query = useStrainShipments(labId, strainId, page)
  return (
    <Section title="Where distributed vials went">
      <Rows labId={labId} query={query} page={page} onOffsetChange={setOffset} />
    </Section>
  )
}

type RowsProps = {
  labId: string
  query: ReturnType<typeof useStrainShipments>
  page: { limit: number; offset: number }
  onOffsetChange: (offset: number) => void
}

function Rows({ labId, query, page, onOffsetChange }: RowsProps) {
  if (query.data === undefined) {
    if (query.isPending) return <Typography>Loading the shipments…</Typography>
    return <LoadError what="the shipments" error={query.error} onRetry={() => void query.refetch()} />
  }
  const { count, results } = query.data
  const stale = <StaleNotice what="the shipments" query={query} />
  if (count === 0)
    return (
      <>
        {stale}
        <Typography>No vial of this strain was distributed.</Typography>
      </>
    )
  if (results.length === 0)
    return (
      <>
        {stale}
        <PastTheEnd onFirstPage={() => onOffsetChange(0)} />
      </>
    )
  return (
    <>
      {stale}
      <TableContainer {...scrollable('Shipments')}>
        <Table aria-label="Shipments">
          <TableHead>
            <TableRow>
              <TableCell>Request</TableCell>
              <TableCell>Institution</TableCell>
              <TableCell>Country</TableCell>
              <TableCell>Shipped</TableCell>
              <TableCell>Vials</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {results.map((row) => (
              <TableRow key={row.request}>
                <TableCell>
                  <Link to="/labs/$labId/requests/$requestId" params={{ labId, requestId: row.request }}>
                    {row.number}
                  </Link>
                </TableCell>
                <TableCell sx={{ overflowWrap: 'anywhere' }}>{row.institution}</TableCell>
                <TableCell>{countryName(row.country)}</TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>{day(row.shipped_at)}</TableCell>
                <TableCell>{row.vials}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Pager label="Pages of the shipments" count={count} shown={results.length} limit={page.limit} offset={page.offset} loading={query.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </>
  )
}
