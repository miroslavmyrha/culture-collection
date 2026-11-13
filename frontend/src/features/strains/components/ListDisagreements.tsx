import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'
import { StaleNotice } from '@/components/StaleNotice'
import { Link, Mono, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import type { PageParams } from '@/lib/paging'
import { useStrainDisagreements } from '../api/queries'
import { DISAGREEMENT_LABELS, RESTRICTION_LABELS, type StrainDisagreement } from '../schemas'

type Props = {
  labId: string
  params: PageParams
  /** The page owns the URL: it turns this into a navigation. */
  onOffsetChange: (offset: number) => void
}

type Finding = StrainDisagreement['findings'][number]

/**
 * Every strain of the lab whose classification disagrees with the official lists (#169), a page
 * at a time. The server computes it at the read, so it follows a reclassification and a new
 * reading of a list by itself. Each row links to the strain, where the disagreement is settled
 * with a reason.
 */
export function ListDisagreements({ labId, params, onOffsetChange }: Props) {
  const list = useStrainDisagreements(labId, params)
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the classification check…</Typography>
    return <LoadError what="the classification check" error={list.error} onRetry={() => void list.refetch()} />
  }
  const stale = <StaleNotice what="the classification check" query={list} />
  const { count, results } = list.data
  if (count === 0)
    return (
      <>
        {stale}
        <Typography>No strain of this lab disagrees with the official lists.</Typography>
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
    <section aria-label="Classification check" aria-busy={list.isPlaceholderData}>
      {stale}
      <Typography sx={{ mb: 2 }}>{count === 1 ? '1 strain disagrees with the official lists.' : `${count} strains disagree with the official lists.`}</Typography>
      <TableContainer component={Paper} variant="outlined">
        <Table aria-label="Classification check">
          <TableHead>
            <TableRow>
              <TableCell>Strain</TableCell>
              <TableCell>Taxon</TableCell>
              <TableCell>What disagrees</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {results.map((row) => (
              <TableRow key={row.strain.public_id}>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>
                  <Link to="/labs/$labId/strains/$strainId" params={{ labId, strainId: row.strain.public_id }}>
                    <Mono>{row.strain.accession_number ?? 'Not numbered'}</Mono>
                  </Link>
                </TableCell>
                <TableCell sx={{ overflowWrap: 'anywhere' }}>{row.strain.taxon.name}</TableCell>
                <TableCell sx={{ overflowWrap: 'anywhere' }}>
                  <Stack component="ul" spacing={0.5} sx={{ listStyle: 'none', p: 0, m: 0 }}>
                    {row.findings.map((finding) => (
                      <Typography component="li" variant="body2" key={key(finding)}>
                        {says(finding, row.strain.risk_group)}
                      </Typography>
                    ))}
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Pager label="Classification check pages" count={count} shown={results.length} limit={params.limit} offset={params.offset} loading={list.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </section>
  )
}

/** A finding has no id: its kind, its restriction kind and the entry it names tell them apart. */
const key = (f: Finding) => `${f.disagreement} ${f.restriction_kind} ${f.entry?.public_id ?? ''}`

/** What one finding says, in a sentence that names the entry and the reading it comes from. */
function says(finding: Finding, riskGroup: number): string {
  const entry = finding.entry
  const where = entry === null ? '' : ` (${entry.act}, entry ${entry.code}, ${entry.version} of ${entry.version_date})`
  const label = DISAGREEMENT_LABELS[finding.disagreement]
  if (finding.disagreement === 'risk_group_differs') {
    const accepted = finding.accepted_because === '' ? '' : ` Accepted by the collection: ${finding.accepted_because}`
    return `${label}: the entry states risk group ${entry?.risk_group ?? '?'}, the strain has ${riskGroup}${where}.${accepted}`
  }
  const kind = finding.restriction_kind === '' ? 'a restriction' : RESTRICTION_LABELS[finding.restriction_kind]
  return `${label}: ${kind}${where}.`
}
