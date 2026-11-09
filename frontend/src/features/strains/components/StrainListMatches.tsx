import { useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Mono, Stack, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useStrainListMatches } from '../api/queries'
import { RESTRICTION_LABELS, type Strain } from '../schemas'
import { AddRestrictionDialog, type RestrictionSuggestion, RiskGroupDialog, type RiskGroupSuggestion } from './StrainDialogs'
import { Section } from './parts'

type Props = { labId: string; strain: Strain; canManage: boolean }
type Match = NonNullable<ReturnType<typeof useStrainListMatches>['data']>['results'][number]
type Open = { restriction: RestrictionSuggestion; group?: never; open: boolean } | { group: RiskGroupSuggestion; restriction?: never; open: boolean } | null

const INTRO =
  'What the official lists say about this taxon, matched on its name, the name of its accepted taxon, the name of any synonym of it, or its genus. A suggestion only: nothing here is recorded until somebody records it with a reason.'

/** Which reading of which list a line comes from, so the suggestion can be checked. */
const source = (match: Match) => `${match.act}, ${match.version} of ${match.version_date}`

/** The basis a confirmed risk group suggestion carries: the entry, its list and its version. */
const basisOf = (match: Match) => `${match.name} (${match.act}, entry ${match.code}, ${match.version})`

/**
 * The entries of the official lists that match a strain's taxon (#169). A read: every line says
 * which list and which reading of it says so. Someone who manages strains can take a line into
 * the dialog that records it, where the kind, the entry and the act are filled in and the reason
 * is still theirs to write. The server refuses anything the form would not.
 */
export function StrainListMatches({ labId, strain, canManage }: Props) {
  const matches = useStrainListMatches(labId, strain.public_id)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (next: NonNullable<Open>) => (event: React.MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen(next)
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }

  const held = new Set(strain.restriction_history.filter((r) => r.ended_at === null).map((r) => r.kind))
  return (
    <Section title="Official lists">
      <Typography>{INTRO}</Typography>
      {matches.data === undefined ? (
        matches.isPending ? (
          <Typography>Loading the official lists…</Typography>
        ) : (
          <LoadError what="the official lists" error={matches.error} onRetry={() => void matches.refetch()} />
        )
      ) : (
        <>
          <StaleNotice what="the official lists" query={matches} />
          {matches.data.results.length === 0 ? (
            <Typography>No entry of the official lists names this taxon.</Typography>
          ) : (
            <Stack component="ul" spacing={2} sx={{ listStyle: 'none', p: 0, m: 0 }}>
              {matches.data.results.map((match: Match) => (
                <Stack key={match.public_id} component="li" spacing={0.5}>
                  <Typography sx={{ overflowWrap: 'anywhere' }}>
                    <Mono>{match.code}</Mono> {match.name}
                  </Typography>
                  <Typography variant="body2">{source(match)}</Typography>
                  <Typography variant="body2">
                    {match.restriction_kind !== '' && `Suggests: ${RESTRICTION_LABELS[match.restriction_kind]}${held.has(match.restriction_kind) ? ' (the strain has one)' : ''}. `}
                    {match.risk_group !== null && `States risk group ${match.risk_group}${match.risk_group === strain.risk_group ? ' (the strain has it)' : ''}.`}
                  </Typography>
                  {canManage && match.restriction_kind !== '' && !held.has(match.restriction_kind) && (
                    <Box>
                      <Button onClick={show({ restriction: { kind: match.restriction_kind, reference: match.code, act: match.suggests_act }, open: true })}>
                        Record {RESTRICTION_LABELS[match.restriction_kind]}
                      </Button>
                    </Box>
                  )}
                  {canManage && match.risk_group !== null && match.risk_group !== strain.risk_group && (
                    <Box>
                      <Button onClick={show({ group: { risk_group: String(match.risk_group), basis: basisOf(match), entry: match.public_id }, open: true })}>
                        Use as the risk group basis
                      </Button>
                    </Box>
                  )}
                </Stack>
              ))}
            </Stack>
          )}
        </>
      )}

      {/* Mounted until they have faded out, so onExited can place the focus. */}
      {open?.restriction !== undefined && <AddRestrictionDialog labId={labId} strain={strain} suggestion={open.restriction} open={open.open} onClose={close} onExited={exited} />}
      {open?.group !== undefined && <RiskGroupDialog labId={labId} strain={strain} suggestion={open.group} open={open.open} onClose={close} onExited={exited} />}
    </Section>
  )
}
