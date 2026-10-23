import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Mono, Paper, Typography } from '@/components/ui'
import { useActivity } from '../api/queries'
import { type ActivityLine, actorLabel, moment } from '../schemas'
import { TargetLink } from './TargetLink'

/**
 * The latest events of the person's labs they may read, newest first, one line each: when, which
 * lab, who (the audit's pseudonymous label, or You) and what, linking to its subject. The server
 * picks the events and writes the words; a line never says where a vial is.
 */
export function RecentActivity() {
  const activity = useActivity()
  return (
    <Box component="section" aria-labelledby="activity-heading" sx={{ mb: 4 }}>
      <Typography id="activity-heading" component="h2" variant="h5" sx={{ mb: 1.5 }}>
        Recent activity
      </Typography>
      <Lines query={activity} />
    </Box>
  )
}

function Lines({ query }: { query: ReturnType<typeof useActivity> }) {
  if (query.data === undefined) {
    if (query.isPending) return <Typography>Loading the activity…</Typography>
    return <LoadError what="the activity" error={query.error} onRetry={() => void query.refetch()} />
  }
  const stale = <StaleNotice what="the activity" query={query} />
  const lines = query.data.results
  if (lines.length === 0) return <>{stale}<Typography>Nothing has happened in your labs yet.</Typography></>
  return (
    <>
      {stale}
      <Paper variant="outlined">
        <Box component="ol" aria-label="Recent activity, newest first" sx={{ listStyle: 'none', m: 0, p: 0 }}>
          {keyed(lines).map(([key, line]) => (
            <Line key={key} line={line} />
          ))}
        </Box>
      </Paper>
    </>
  )
}

/** Lines carry no id (an event's id stays on the server): the content, numbered when repeated. */
function keyed(lines: ActivityLine[]): [string, ActivityLine][] {
  const seen = new Map<string, number>()
  return lines.map((line) => {
    const base = `${line.occurred_at} ${line.lab} ${line.actor} ${line.summary}`
    const n = (seen.get(base) ?? 0) + 1
    seen.set(base, n)
    return [`${base} ${n}`, line]
  })
}

function Line({ line }: { line: ActivityLine }) {
  return (
    <Box component="li" sx={{ px: 2, py: 0.75, display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 1, '& + &': { borderTop: 1, borderColor: 'divider' } }}>
      <Typography component="time" variant="body2" color="text.secondary" dateTime={line.occurred_at} sx={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
        {moment(line.occurred_at)}
      </Typography>
      <Typography component="span" variant="body2" color="text.secondary">
        <Mono>{line.lab_code}</Mono>
      </Typography>
      <Typography component="span" variant="body2" sx={{ overflowWrap: 'anywhere' }}>
        <Box component="span" sx={{ fontWeight: 600 }}>
          {actorLabel(line.actor)}
        </Box>{' '}
        <TargetLink labId={line.lab} target={line.target} id={line.target_id}>
          {line.summary}
        </TargetLink>
      </Typography>
    </Box>
  )
}
