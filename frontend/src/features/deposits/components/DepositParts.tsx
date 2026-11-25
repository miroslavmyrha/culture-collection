import { Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@/components/ui'
import { countryName } from '@/lib/countries'
import type { useDeposit } from '../api/queries'
import { ABS_SCOPE_LABELS, CONDITION_LABELS, DECISION_LABELS, type Deposit, depositorLabel, mtaLabel, type Terms, USE_LABELS } from '../schemas'
import { scrollable } from './scroll'
import { day } from '@/lib/dates'
import { Facts, Section } from '@/components/DetailParts'
import { DetailUnavailable } from '@/components/DetailUnavailable'


/** A value that may be empty, or the words for empty. */
const orElse = (value: string | null | undefined, empty: string): string => (value ? value : empty)

const mtaText = (mta: Terms['mta']): string => (mta ? mtaLabel(mta) : 'None')

/** What the deposit page shows while it has no deposit: loading, not found, or the load error, each with its title. */
export function DepositUnavailable({ deposit }: { deposit: ReturnType<typeof useDeposit> }) {
  return <DetailUnavailable query={deposit} noun="deposit" notFound="The deposit does not exist, or it is not in this lab." />
}

/** The receipt: who deposited, when, in what condition. */
export function ReceiptFacts({ deposit: d }: { deposit: Deposit }) {
  const passages = d.depositor_passages === null ? 'Not stated' : String(d.depositor_passages)
  return (
    <Facts
      rows={[
        ['Depositor', depositorLabel(d.depositor)],
        ['Received on', d.received_on],
        ['Condition on arrival', CONDITION_LABELS[d.condition]],
        ['Note on the condition', orElse(d.condition_note, 'None')],
        ['Passages stated by the depositor', passages],
      ]}
    />
  )
}

/** The uses the MAT covers: only for material in scope; none ticked says nothing goes to a third party. */
function matRows(terms: Terms): [string, string][] {
  if (terms.abs_scope !== 'in_scope') return []
  const covered = terms.mat_uses.map((use) => USE_LABELS[use]).join(', ')
  return [['Uses the MAT covers', orElse(covered, 'None: nothing goes to a third party')]]
}

/** Why a version replaced the one before, when it says. */
function reasonRows(terms: Terms): [string, string][] {
  return terms.reason ? [['Why this version', terms.reason]] : []
}

function UsesTable({ terms }: { terms: Terms }) {
  return (
    <TableContainer component={Paper} variant="outlined" {...scrollable('Uses')}>
      <Table aria-label="Uses" size="small">
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
              <TableCell>{DECISION_LABELS[u.decision]}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

export function TermsFacts({ terms }: { terms: Terms }) {
  const country = terms.country_of_origin ? countryName(terms.country_of_origin) : 'Unknown'
  return (
    <>
      <Facts
        rows={[
          ['MTA', mtaText(terms.mta)],
          ['ABS scope', ABS_SCOPE_LABELS[terms.abs_scope]],
          ['Country of origin', country],
          ['Collection date', orElse(terms.collection_date, 'Unknown')],
          ['IRCC', orElse(terms.ircc, 'None')],
          ['Permit reference', orElse(terms.permit_reference, 'None')],
          ['PIC reference', orElse(terms.pic_reference, 'None')],
          ['MAT reference', orElse(terms.mat_reference, 'None')],
          ...matRows(terms),
          ...reasonRows(terms),
        ]}
      />
      <UsesTable terms={terms} />
    </>
  )
}

export function TermsHistory({ rows }: { rows: Terms[] }) {
  return (
    <TableContainer component={Paper} variant="outlined" {...scrollable('Earlier terms')}>
      <Table aria-label="Earlier terms" size="small">
        <TableHead>
          <TableRow>
            <TableCell>Version</TableCell>
            <TableCell>From</TableCell>
            <TableCell>MTA</TableCell>
            <TableCell>ABS scope</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((t) => (
            <TableRow key={t.public_id}>
              <TableCell>{t.version}</TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{day(t.created_at)}</TableCell>
              <TableCell sx={{ overflowWrap: 'anywhere' }}>{mtaText(t.mta)}</TableCell>
              <TableCell>{ABS_SCOPE_LABELS[t.abs_scope]}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

export { day, Section }
