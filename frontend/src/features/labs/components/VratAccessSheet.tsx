import { type ReactNode, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Link, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@/components/ui'
import { moment } from '@/lib/activity'
import { useVratAccess } from '../api/queries'
import { endedBy, type Lab, personName, type VratAccess } from '../schemas'

type Props = {
  lab: Pick<Lab, 'public_id' | 'name' | 'code'>
  /** The lab's VRAT permit in force, from the permits feature (the page composes it). */
  renderPermit: () => ReactNode
}

const printSx = { '@media print': { color: '#000', fontSize: '10pt' } }

/**
 * The lab's VRAT access list as a page to print and hand to SÚJB (act 281/2002 Sb., § 14a(4)):
 * the lab, its VRAT permit in force, every person who is or was on the list with from and until,
 * who put them on and took them off and why, and when it was printed. On paper only the list
 * shows: the bar, the lab tabs and the buttons are not printed. For managers; the page shows
 * nothing of it to anybody else.
 */
export function VratAccessSheet({ lab, renderPermit }: Props) {
  const list = useVratAccess(lab.public_id)
  const title = `VRAT access list of ${lab.name}`
  return (
    <Box sx={printSx}>
      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mb: 2, displayPrint: 'none' }}>
        <Link to="/labs/$labId" params={{ labId: lab.public_id }}>
          Back to {lab.name}
        </Link>
      </Stack>
      <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
        {title}
      </Typography>
      <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 2, rowGap: 0.5, m: 0, mb: 2, '& dd': { m: 0 } }}>
        <dt>Lab</dt>
        <dd>
          {lab.name} ({lab.code})
        </dd>
        <dt>Permit</dt>
        <dd>{renderPermit()}</dd>
        <dt>Rule</dt>
        <dd>Act 281/2002 Sb., § 14a(4): the list of the people who have access to highly risky agents (VRAT)</dd>
        <dt>Printed on</dt>
        <dd>
          <PrintedOn />
        </dd>
      </Box>
      <Rows list={list} />
    </Box>
  )
}

/** The moment the page was opened: the list below is the data loaded then. */
function PrintedOn() {
  const [now] = useState(() => new Date().toISOString())
  return <time dateTime={now}>{moment(now)}</time>
}

function Rows({ list }: { list: ReturnType<typeof useVratAccess> }) {
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the VRAT access list…</Typography>
    return <LoadError what="the VRAT access list" error={list.error} onRetry={() => void list.refetch()} />
  }
  return (
    <>
      <StaleNotice what="the VRAT access list" query={list} />
      <Summary entries={list.data} />
      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mb: 2, displayPrint: 'none' }}>
        <Button variant="contained" onClick={() => window.print()}>
          Print
        </Button>
      </Stack>
      {list.data.length > 0 && (
        // It may scroll sideways on a narrow screen: a named region and a tab stop (WCAG 2.1.1).
        <Box
          component="section"
          tabIndex={0}
          aria-label="VRAT access table"
          sx={{ overflowX: 'auto', '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 }, '@media print': { overflow: 'visible' } }}
        >
          <Table size="small" aria-label="VRAT access list" sx={{ '@media print': { '& th, & td': { color: '#000', borderColor: '#000', fontSize: '10pt' } } }}>
            <TableHead>
              <TableRow>
                <TableCell>Person</TableCell>
                <TableCell>From</TableCell>
                <TableCell>Until</TableCell>
                <TableCell>Put on by, why</TableCell>
                <TableCell>Ended by, why</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {list.data.map((e) => (
                <AccessRow key={e.public_id} entry={e} />
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </>
  )
}

/** How many people have access now, and whether anybody was ever on the list. */
function Summary({ entries }: { entries: VratAccess[] }) {
  const open = entries.filter((e) => e.ended_at === null).length
  return (
    <Typography sx={{ mb: 2 }}>
      {open === 0 ? 'Nobody has access now.' : `${open} ${open === 1 ? 'person has' : 'people have'} access now.`}{' '}
      {entries.length === 0 ? 'Nobody was ever on the list.' : 'Entries that ended stay on the list with their end.'}
    </Typography>
  )
}

/** One entry: the person, from and until, who put them on and took them off, and why. */
function AccessRow({ entry }: { entry: VratAccess }) {
  return (
    <TableRow>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        {personName(entry) || entry.username}
        {personName(entry) && (
          <Box component="span" sx={{ display: 'block' }}>
            {entry.username}
          </Box>
        )}
      </TableCell>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>
        <time dateTime={entry.granted_at}>{moment(entry.granted_at)}</time>
      </TableCell>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>{entry.ended_at === null ? 'has access' : <time dateTime={entry.ended_at}>{moment(entry.ended_at)}</time>}</TableCell>
      <TableCell sx={{ overflowWrap: 'break-word' }}>
        {entry.granted_by}: {entry.reason}
      </TableCell>
      <TableCell sx={{ overflowWrap: 'break-word' }}>{entry.ended_at === null ? '' : `${endedBy(entry)}: ${entry.end_reason}`}</TableCell>
    </TableRow>
  )
}
