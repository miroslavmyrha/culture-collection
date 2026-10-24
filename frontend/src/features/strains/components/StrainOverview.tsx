import { type MouseEvent, useRef, useState } from 'react'
import { Box, Button, Link, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { STRAIN_TONES } from '@/lib/tones'
import { countryName, GMO_CATEGORY_LABELS, PATHOGENICITY_LABELS, RESTRICTION_LABELS, STATUS_LABELS, type Strain } from '../schemas'
import { day, Facts, scrollable, Section } from './parts'
import { EndRestrictionDialog } from './StrainDialogs'
import { ActiveTerms } from './StrainTerms'

type Props = { labId: string; strain: Strain; canManage: boolean }

type Restriction = Strain['restriction_history'][number]
type Open = { restriction: Restriction; open: boolean } | null

/**
 * What the strain is (#19): its facts, its restrictions, the terms of use in force and how it was
 * identified, from the strain the page already holds; only the terms are a read of their own.
 */
export function StrainOverview({ labId, strain: s, canManage }: Props) {
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const end = (restriction: Restriction) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ restriction, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }
  const active = s.restriction_history.filter((r) => r.ended_at === null)
  const ended = s.restriction_history.filter((r) => r.ended_at !== null)
  return (
    <>
      <Section title="Facts">
        <Facts
          rows={[
            ['Name as received', s.name_as_received],
            ['Status', <StatusChip key="status" tone={STRAIN_TONES[s.status]}>{STATUS_LABELS[s.status]}</StatusChip>],
            ['Risk group', String(s.risk_group)],
            ['Animal pathogenicity', PATHOGENICITY_LABELS[s.animal_pathogenicity]],
            ['Plant pathogenicity', PATHOGENICITY_LABELS[s.plant_pathogenicity]],
            ['Isolation source', s.isolation_source || 'Unknown'],
            ['Country of origin', s.country_of_origin ? countryName(s.country_of_origin) : 'Unknown'],
            ['Isolation date', s.isolation_date || 'Unknown'],
            ['Accessioned', day(s.created_at)],
          ]}
        />
      </Section>

      <Section title="Restrictions">
        {active.length === 0 ? (
          <Typography>None. The agent is on no regulatory list.</Typography>
        ) : (
          <RestrictionTable rows={active} caption="Current restrictions" end={canManage ? end : undefined} />
        )}
        {ended.length > 0 && <RestrictionTable rows={ended} caption="Ended restrictions" />}
      </Section>

      <Section title="Terms of use">
        <ActiveTerms labId={labId} strainId={s.public_id} />
        <Typography>
          <Link to="/labs/$labId/strains/$strainId/terms" params={{ labId, strainId: s.public_id }}>
            Every version of the terms
          </Link>
        </Typography>
      </Section>

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
              {s.identifications.map((i) => (
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

      {/* Mounted until it has faded out, so onExited can place the focus. */}
      {open && <EndRestrictionDialog labId={labId} strain={s} restriction={open.restriction} open={open.open} onClose={close} onExited={exited} />}
    </>
  )
}

type TableProps = {
  rows: Restriction[]
  caption: string
  end?: ((r: Restriction) => (event: MouseEvent<HTMLButtonElement>) => void) | undefined
}

function RestrictionTable({ rows, caption, end }: TableProps) {
  const isEnded = rows.some((r) => r.ended_at !== null)
  return (
    <TableContainer {...scrollable(caption)}>
      <Table aria-label={caption}>
        <TableHead>
          <TableRow>
            <TableCell>Kind</TableCell>
            <TableCell>List entry</TableCell>
            <TableCell>Since</TableCell>
            {isEnded && <TableCell>Ended</TableCell>}
            {end && <TableCell>Action</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.public_id}>
              <TableCell>
                <StatusChip tone="regulated">{RESTRICTION_LABELS[r.kind]}</StatusChip>
              </TableCell>
              <TableCell sx={{ overflowWrap: 'anywhere' }}>
                {r.reference}
                {r.act && ` (read in ${r.act})`}
                {r.gmo_category !== null && `, category ${GMO_CATEGORY_LABELS[r.gmo_category] ?? r.gmo_category}`}
              </TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{day(r.created_at)}</TableCell>
              {isEnded && (
                <TableCell>
                  {r.ended_at && day(r.ended_at)}: {r.end_reason}
                </TableCell>
              )}
              {end && (
                <TableCell>
                  <Button onClick={end(r)} aria-label={`End restriction ${r.reference}`}>
                    End
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
