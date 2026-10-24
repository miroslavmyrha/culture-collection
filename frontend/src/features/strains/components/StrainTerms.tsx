import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Link, Mono, Paper, StatusChip, type Tone, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { ABS_SCOPE_LABELS, DECISION_LABELS, type Decision, USE_LABELS } from '@/lib/terms'
import { useStrainTerms } from '../api/queries'
import { countryName, type Terms } from '../schemas'
import { day, Facts, scrollable, Section } from './parts'

type Props = { labId: string; strainId: string }

/** What a use may do, at a glance: a refusal and a question to the depositor need a look. */
const DECISION_TONES: Record<Decision, Tone | undefined> = { permit: undefined, deny: 'danger', on_request: 'warning' }

/**
 * The terms in force, on the overview: what the strain may be used for and under which MTA,
 * which every role that sees the strain asks (#78). A read of its own, so a failure leaves the
 * rest of the overview.
 */
export function ActiveTerms({ labId, strainId }: Props) {
  const terms = useStrainTerms(labId, strainId)
  if (terms.data === undefined) {
    if (terms.isPending) return <Typography>Loading the terms…</Typography>
    return <LoadError what="the terms" error={terms.error} onRetry={() => void terms.refetch()} />
  }
  const active = terms.data.versions.find((v) => v.is_active)
  return (
    <>
      <StaleNotice what="the terms" query={terms} />
      {active === undefined ? (
        <Typography>No terms of use are recorded: the strain came from no deposit.</Typography>
      ) : (
        <>
          <Typography>
            Version {active.version}, in force since {day(active.created_at)}. <Mta labId={labId} terms={active} opens={terms.data.deposit !== null} />
          </Typography>
          <UseTable terms={active} caption="Uses of the terms in force" />
        </>
      )}
    </>
  )
}

/**
 * Every version of the strain's terms, newest first (#19): what each allowed, under which MTA,
 * the ABS facts it recorded and why it replaced the one before. The deposit they belong to for
 * those who may open deposits.
 */
export function StrainTerms({ labId, strainId }: Props) {
  const terms = useStrainTerms(labId, strainId)
  if (terms.data === undefined) {
    if (terms.isPending) return <Typography>Loading the terms…</Typography>
    return <LoadError what="the terms" error={terms.error} onRetry={() => void terms.refetch()} />
  }
  const { deposit, versions } = terms.data
  return (
    <Section title="Terms of use">
      <StaleNotice what="the terms" query={terms} />
      {versions.length === 0 ? (
        <Typography>No terms of use are recorded: the strain came from no deposit.</Typography>
      ) : (
        <>
          <Typography>
            {versions.length === 1 ? 'One version.' : `${versions.length} versions, newest first.`}
            {deposit !== null && (
              <>
                {' '}
                <Link to="/labs/$labId/deposits/$depositId" params={{ labId, depositId: deposit }}>
                  Open the deposit
                </Link>
              </>
            )}
          </Typography>
          {versions.map((v, i) => (
            <Version key={v.public_id} labId={labId} terms={v} until={i > 0 ? versions[i - 1]?.created_at : undefined} opens={deposit !== null} />
          ))}
        </>
      )}
    </Section>
  )
}

function Version({ labId, terms: t, until, opens }: { labId: string; terms: Terms; until: string | undefined; opens: boolean }) {
  const title = `Version ${t.version}`
  const when = t.is_active ? `in force since ${day(t.created_at)}` : `from ${day(t.created_at)}${until ? ` to ${day(until)}` : ''}`
  return (
    <Paper component="article" variant="outlined" aria-label={title} sx={{ p: 2 }}>
      <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
        {title}{' '}
        {t.is_active ? <StatusChip tone="success">In force</StatusChip> : <StatusChip tone="neutral">Replaced</StatusChip>}
      </Typography>
      <Facts
        rows={[
          ['Valid', when],
          ...(t.version > 1 ? ([['Why it replaced the one before', t.reason]] as [string, string][]) : []),
          ['MTA', <Mta key="mta" labId={labId} terms={t} opens={opens} />],
          ['ABS (Regulation 511/2014)', ABS_SCOPE_LABELS[t.abs_scope]],
          ['Country of origin', t.country_of_origin ? countryName(t.country_of_origin) : 'Not recorded'],
          ['Collection date', t.collection_date || 'Not recorded'],
          ...absReferences(t),
        ]}
      />
      <Box sx={{ mt: 2 }}>
        <UseTable terms={t} caption={`Uses of version ${t.version}`} />
      </Box>
    </Paper>
  )
}

/** The references of material in scope of 511/2014, the ones recorded. */
function absReferences(t: Terms): [string, string][] {
  const rows: [string, string][] = [
    ['Prior informed consent', t.pic_reference],
    ['Mutually agreed terms', t.mat_reference],
    ['Certificate of compliance (IRCC)', t.ircc],
    ['Permit of access', t.permit_reference],
  ]
  const shown = rows.filter(([, value]) => value !== '')
  if (t.mat_uses.length > 0) shown.push(['Uses the MAT covers', t.mat_uses.map((use) => USE_LABELS[use]).join(', ')])
  return shown
}

function Mta({ labId, terms, opens }: { labId: string; terms: Terms; opens: boolean }) {
  const mta = terms.mta
  if (mta === null) return <>No MTA.</>
  const text = (
    <>
      MTA <Mono>{mta.code}</Mono> version {mta.version}, {mta.title}
    </>
  )
  // The template page needs deposits.view: a link only for those the server gave the deposit.
  if (!opens) return text
  return (
    <Link to="/labs/$labId/mta-templates/$templateId" params={{ labId, templateId: mta.public_id }}>
      {text}
    </Link>
  )
}

function UseTable({ terms, caption }: { terms: Terms; caption: string }) {
  return (
    // Two short columns: as wide as they need, not the page.
    <TableContainer {...scrollable(caption)} sx={{ ...scrollable(caption).sx, maxWidth: 640 }}>
      <Table aria-label={caption} size="small">
        <TableHead>
          <TableRow>
            <TableCell>Use</TableCell>
            <TableCell>Decision</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {terms.uses.map((u) => (
            <TableRow key={u.use}>
              <TableCell>{USE_LABELS[u.use]}</TableCell>
              <TableCell>
                <StatusChip tone={DECISION_TONES[u.decision]}>{DECISION_LABELS[u.decision]}</StatusChip>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
