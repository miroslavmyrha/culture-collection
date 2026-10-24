import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Link, Paper, Typography } from '@/components/ui'
import type { PageParams } from '@/lib/paging'
import { useStrainHistory } from '../api/queries'
import { actorLabel, type HistoryLine, moment } from '../schemas'
import { Section } from './parts'

type Props = { labId: string; strainId: string; page: PageParams; onOffsetChange: (offset: number) => void }

/**
 * Everything that happened to the strain that the person may read, newest first, one line each
 * (#19): when, who (the audit's pseudonymous label, or You) and what. The server picks the events
 * by the rules of the activity on Home and writes the words; a line never says where a vial is.
 * A page at a time, with the count of every line.
 */
export function StrainHistory({ labId, strainId, page, onOffsetChange }: Props) {
  const history = useStrainHistory(labId, strainId, page)
  return (
    <Section title="History">
      <Lines labId={labId} query={history} page={page} onOffsetChange={onOffsetChange} />
    </Section>
  )
}

type LinesProps = { labId: string; query: ReturnType<typeof useStrainHistory>; page: PageParams; onOffsetChange: (offset: number) => void }

function Lines({ labId, query, page, onOffsetChange }: LinesProps) {
  if (query.data === undefined) {
    if (query.isPending) return <Typography>Loading the history…</Typography>
    return <LoadError what="the history" error={query.error} onRetry={() => void query.refetch()} />
  }
  const { count, results } = query.data
  const stale = <StaleNotice what="the history" query={query} />
  if (count === 0) return <>{stale}<Typography>Nothing you may read has happened to the strain yet.</Typography></>
  if (results.length === 0) return <>{stale}<PastTheEnd onFirstPage={() => onOffsetChange(0)} /></>
  return (
    <>
      {stale}
      <Typography>
        {count === 1 ? 'One event.' : `${count} events, newest first.`}
      </Typography>
      <Paper variant="outlined">
        <Box component="ol" aria-label="History, newest first" sx={{ listStyle: 'none', m: 0, p: 0 }}>
          {keyed(results).map(([key, line]) => (
            <Line key={key} labId={labId} line={line} />
          ))}
        </Box>
      </Paper>
      <Pager label="Pages of the history" count={count} shown={results.length} limit={page.limit} offset={page.offset} loading={query.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </>
  )
}

/** Lines carry no id (an event's id stays on the server): the content, numbered when repeated. */
function keyed(lines: HistoryLine[]): [string, HistoryLine][] {
  const seen = new Map<string, number>()
  return lines.map((line) => {
    const base = `${line.occurred_at} ${line.actor} ${line.summary}`
    const n = (seen.get(base) ?? 0) + 1
    seen.set(base, n)
    return [`${base} ${n}`, line]
  })
}

function Line({ labId, line }: { labId: string; line: HistoryLine }) {
  return (
    <Box component="li" sx={{ px: 2, py: 0.75, display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 1, '& + &': { borderTop: 1, borderColor: 'divider' } }}>
      <Typography component="time" variant="body2" color="text.secondary" dateTime={line.occurred_at} sx={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
        {moment(line.occurred_at)}
      </Typography>
      <Typography component="span" variant="body2" sx={{ overflowWrap: 'anywhere' }}>
        <Box component="span" sx={{ fontWeight: 600 }}>
          {actorLabel(line.actor)}
        </Box>{' '}
        <Summary labId={labId} line={line} />
      </Typography>
    </Box>
  )
}

/**
 * The line's words, linked to a page of its subject that is not this strain: a request or a
 * deposit. A line about the strain itself, its material included, links nowhere: it is here.
 */
function Summary({ labId, line }: { labId: string; line: HistoryLine }) {
  if (line.target === 'request' && line.target_id)
    return (
      <Link to="/labs/$labId/requests/$requestId" params={{ labId, requestId: line.target_id }}>
        {line.summary}
      </Link>
    )
  if (line.target === 'deposit' && line.target_id)
    return (
      <Link to="/labs/$labId/deposits/$depositId" params={{ labId, depositId: line.target_id }}>
        {line.summary}
      </Link>
    )
  return <>{line.summary}</>
}
