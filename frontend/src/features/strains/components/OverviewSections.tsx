import type { ReactNode } from 'react'
import { Box, Link, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { ATMOSPHERE_LABELS, temperatureText } from '@/lib/growth'
import { STRAIN_TONES } from '@/lib/tones'
import { CAUSE_LABELS, countryName, type DeaccessionProposal, FINAL_USE_LABELS, PATHOGENICITY_LABELS, STATUS_LABELS, type Strain } from '../schemas'
import { day, Facts, scrollable, Section } from './parts'
import { ActiveTerms } from './StrainTerms'

type Row = [string, ReactNode]

const orUnknown = (value: string | null | undefined): string => value || 'Unknown'

/** The final use of a deaccessioned strain's material, a row only when one was recorded. */
export function finalUseRows(finalUse: DeaccessionProposal['final_use']): Row[] {
  return finalUse ? [['Final use', FINAL_USE_LABELS[finalUse]]] : []
}

/** Why and when the strain left the collection. */
export function DeaccessionSection({ deaccession: d }: { deaccession: NonNullable<Strain['deaccession']> }) {
  return (
    <Section title="Deaccession">
      <Facts rows={[['Left the collection', day(d.deaccessioned_at)], ['Cause', CAUSE_LABELS[d.cause]], ['Reason', d.reason], ...finalUseRows(d.final_use)]} />
      <Typography>Its number is never given to another strain, and its history stays.</Typography>
    </Section>
  )
}

/** The basis of a strain's risk group as the facts show it, with the annex 7 entry it cites. */
function basisOfGroup(s: Strain): string {
  if (!s.risk_group_basis) return 'From the accession'
  return s.risk_group_entry === null ? s.risk_group_basis : `${s.risk_group_basis} (annex 7, entry ${s.risk_group_entry})`
}

/** The deposit the strain came from, named as its own page names it (#154). */
function DepositLink({ labId, deposit }: { labId: string; deposit: NonNullable<Strain['deposit']> }) {
  return (
    <Link to="/labs/$labId/deposits/$depositId" params={{ labId, depositId: deposit.public_id }}>
      Deposit {deposit.name_as_received}
    </Link>
  )
}

/** #154: the server names the deposit only to those who may open deposits in the lab. */
function depositRows(labId: string, deposit: Strain['deposit']): Row[] {
  return deposit ? [['Came from', <DepositLink key="deposit" labId={labId} deposit={deposit} />]] : []
}

function originRows(s: Strain): Row[] {
  return [
    ['Isolation source', orUnknown(s.isolation_source)],
    ['Country of origin', s.country_of_origin ? countryName(s.country_of_origin) : 'Unknown'],
    ['Isolation date', orUnknown(s.isolation_date)],
  ]
}

/** What the strain is: its name, status, risk group and where it came from. */
export function FactsSection({ labId, strain: s }: { labId: string; strain: Strain }) {
  return (
    <Section title="Facts">
      <Facts
        rows={[
          ['Name as received', s.name_as_received],
          ...depositRows(labId, s.deposit),
          ['Status', <StatusChip key="status" tone={STRAIN_TONES[s.status]}>{STATUS_LABELS[s.status]}</StatusChip>],
          ['Risk group', String(s.risk_group)],
          // #174 and #169: what the group rests on, in the person's words, and the entry of
          // annex 7 it was read in where it was read in one. Only a strain accessioned before
          // #169 has no basis at all.
          ['Basis of the risk group', basisOfGroup(s)],
          ['Animal pathogenicity', PATHOGENICITY_LABELS[s.animal_pathogenicity]],
          ['Plant pathogenicity', PATHOGENICITY_LABELS[s.plant_pathogenicity]],
          ...originRows(s),
          ['Accessioned', day(s.created_at)],
        ]}
      />
    </Section>
  )
}

/** The medium by name, with its composition reference and whether it is retired. */
function mediumText(medium: NonNullable<Strain['growth']['medium']>): string {
  const reference = medium.composition_reference ? `, ${medium.composition_reference}` : ''
  return `${medium.name}${reference}${medium.retired_at ? ' (retired)' : ''}`
}

/** The strain's own growth conditions. */
export function GrowthSection({ growth }: { growth: Strain['growth'] }) {
  return (
    <Section title="Growth conditions">
      <Facts
        rows={[
          ['Medium', growth.medium ? mediumText(growth.medium) : 'Not recorded'],
          ['Temperature', temperatureText(growth) || 'Not recorded'],
          ['Atmosphere', growth.atmosphere ? ATMOSPHERE_LABELS[growth.atmosphere] : 'Not recorded'],
        ]}
      />
    </Section>
  )
}

/** The terms of use in force, and the way to every version of them. */
export function TermsSection({ labId, strainId }: { labId: string; strainId: string }) {
  return (
    <Section title="Terms of use">
      <ActiveTerms labId={labId} strainId={strainId} />
      <Typography>
        <Link to="/labs/$labId/strains/$strainId/terms" params={{ labId, strainId }}>
          Every version of the terms
        </Link>
      </Typography>
    </Section>
  )
}

/** Every identification of the strain, the current one marked. */
export function IdentificationSection({ identifications }: { identifications: Strain['identifications'] }) {
  return (
    <Section title="Identification history">
      <TableContainer {...scrollable('Identification history')}>
        <Table aria-label="Identification history">
          <TableHead>
            <TableRow>
              <TableCell>Identified on</TableCell>
              <TableCell>Taxon</TableCell>
              <TableCell>Method</TableCell>
              <TableCell>Reason</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {identifications.map((i) => (
              <TableRow key={i.public_id}>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>
                  {i.identified_on}
                  {i.is_current && <Box component="span"> (current)</Box>}
                </TableCell>
                <TableCell>
                  <i>{i.taxon.name}</i> {i.taxon.authority}
                </TableCell>
                <TableCell>{i.method}</TableCell>
                <TableCell>{i.reason}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Section>
  )
}
