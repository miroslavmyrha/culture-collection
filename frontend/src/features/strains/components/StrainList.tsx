import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'
import { Button, Link, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { useFocusReturnOnUnmount } from '@/lib/focus'
import { useStrainList } from '../api/queries'
import { hasFilters, RESTRICTION_LABELS, STATUS_LABELS, type StrainListParams } from '../schemas'

type Props = {
  labId: string
  params: StrainListParams
  /** The page owns the URL: it turns a new offset into a navigation. */
  onOffsetChange: (offset: number) => void
  onClearFilters: () => void
}

/** The lab's strains by accession number, filtered by the URL, a page at a time. */
export function StrainList({ labId, params, onOffsetChange, onClearFilters }: Props) {
  const list = useStrainList(labId, params)
  if (list.isPending) return <Typography>Loading the strains…</Typography>
  if (list.isError) return <LoadError what="the strains" error={list.error} onRetry={() => void list.refetch()} />
  const { count, results } = list.data
  if (count === 0 && hasFilters(params)) return <NoMatch onClearFilters={onClearFilters} />
  if (count === 0) return <Typography>The lab has no strains yet.</Typography>
  if (results.length === 0) return <PastTheEnd onFirstPage={() => onOffsetChange(0)} />
  return (
    <section aria-label="Strains" aria-busy={list.isPlaceholderData}>
      <TableContainer component={Paper} variant="outlined">
        <Table aria-label="Strains">
          <TableHead>
            <TableRow>
              <TableCell>Number</TableCell>
              <TableCell>Name as received</TableCell>
              <TableCell>Taxon</TableCell>
              <TableCell>Risk group</TableCell>
              <TableCell>Restrictions</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {results.map((strain) => (
              <TableRow key={strain.public_id}>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>
                  <Link to="/labs/$labId/strains/$strainId" params={{ labId, strainId: strain.public_id }}>
                    {strain.accession_number ?? 'pending'}
                  </Link>
                </TableCell>
                <TableCell>{strain.name_as_received}</TableCell>
                <TableCell>
                  <i>{strain.taxon.name}</i>
                </TableCell>
                <TableCell>{strain.risk_group}</TableCell>
                <TableCell>{strain.restrictions.length === 0 ? 'None' : strain.restrictions.map((r) => RESTRICTION_LABELS[r.kind]).join(', ')}</TableCell>
                <TableCell>{STATUS_LABELS[strain.status]}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Pager
        label="Strain pages"
        count={count}
        shown={results.length}
        limit={params.limit}
        offset={params.offset}
        loading={list.isPlaceholderData}
        onOffsetChange={onOffsetChange}
      />
    </section>
  )
}

/** No strain matches. "Clear filters" goes away with this text: focus then moves on (focus.ts). */
function NoMatch({ onClearFilters }: { onClearFilters: () => void }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Typography>
      No strain matches these filters.{' '}
      <Button
        onClick={(event) => {
          remember(event.currentTarget)
          onClearFilters()
        }}
      >
        Clear filters
      </Button>
    </Typography>
  )
}
