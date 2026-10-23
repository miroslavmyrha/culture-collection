import { type MouseEvent, type ReactNode, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Mono, PageTitle, Paper, Stack, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { STRAIN_TONES } from '@/lib/tones'
import { isApiError } from '@/lib/api'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useStrain } from '../api/queries'
import { countryName, GMO_CATEGORY_LABELS, PATHOGENICITY_LABELS, RESTRICTION_LABELS, STATUS_LABELS, type Strain } from '../schemas'
import { AddRestrictionDialog, EndRestrictionDialog, ReclassifyDialog, RiskGroupDialog } from './StrainDialogs'

type Props = {
  labId: string
  strainId: string
  canManage: boolean
  /** What the page puts under the restrictions: the strain's passages, batches and vials. */
  renderMaterial?: (strain: Strain) => ReactNode
}

type Restriction = Strain['restriction_history'][number]
type Open = { kind: 'reclassify' | 'risk' | 'add' | 'end'; restriction?: Restriction; open: boolean } | null

/** The local calendar day of a time, as YYYY-MM-DD (the identification dates are local days too). */
const date = (iso: string) => new Date(iso).toLocaleDateString('sv')

/** One strain: its number, current taxon, biosafety facts, origin and its whole history. */
export function StrainDetail({ labId, strainId, canManage, renderMaterial }: Props) {
  const strain = useStrain(labId, strainId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (kind: NonNullable<Open>['kind'], restriction?: Restriction) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ kind, restriction, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }

  if (strain.data === undefined) {
    if (strain.isPending)
      return (
        <>
          <PageTitle>Loading the strain</PageTitle>
          <Typography>Loading the strain…</Typography>
        </>
      )
    // 404 means "not in this lab" as much as "does not exist": the text says both.
    if (isApiError(strain.error, 404))
      return (
        <>
          <PageTitle>Strain not found</PageTitle>
          <Typography component="h1" variant="h4" gutterBottom>
            Strain not found
          </Typography>
          <Typography>The strain does not exist, or it is not in this lab.</Typography>
        </>
      )
    return (
      <>
        <PageTitle>Could not load the strain</PageTitle>
        <LoadError what="the strain" error={strain.error} onRetry={() => void strain.refetch()} />
      </>
    )
  }
  const s = strain.data
  const number = s.accession_number ?? 'Pending strain'
  const active = s.restriction_history.filter((r) => r.ended_at === null)
  const ended = s.restriction_history.filter((r) => r.ended_at !== null)
  return (
    <>
      <PageTitle>{number}</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
        <Mono>{number}</Mono>
      </Typography>
      <StaleNotice what="the strain" query={strain} />
      <Typography sx={{ mb: 3 }}>
        <i>{s.taxon.name}</i> {s.taxon.authority}
      </Typography>

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
          ['Accessioned', date(s.created_at)],
        ]}
      />

      {canManage && (
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', my: 3 }}>
          <Button variant="outlined" onClick={show('reclassify')}>
            Reclassify
          </Button>
          <Button variant="outlined" onClick={show('risk')}>
            Change risk group
          </Button>
          <Button variant="outlined" onClick={show('add')}>
            Add a restriction
          </Button>
        </Stack>
      )}

      <Section title="Restrictions">
        {active.length === 0 ? (
          <Typography>None. The agent is on no regulatory list.</Typography>
        ) : (
          <RestrictionTable rows={active} caption="Current restrictions" end={canManage ? (r) => show('end', r) : undefined} />
        )}
        {ended.length > 0 && <RestrictionTable rows={ended} caption="Ended restrictions" />}
      </Section>

      {renderMaterial?.(s)}

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

      {/* Mounted until they have faded out, so onExited can place the focus. */}
      {open?.kind === 'reclassify' && <ReclassifyDialog labId={labId} strain={s} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'risk' && <RiskGroupDialog labId={labId} strain={s} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'add' && <AddRestrictionDialog labId={labId} strain={s} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'end' && open.restriction && (
        <EndRestrictionDialog labId={labId} strain={s} restriction={open.restriction} open={open.open} onClose={close} onExited={exited} />
      )}
    </>
  )
}

/**
 * A table that may scroll sideways on a narrow screen. Its container is a named region and a
 * tab stop, so a keyboard user can scroll it with the arrow keys also when no cell holds a
 * control (WCAG 2.1.1; axe scrollable-region-focusable).
 */
const scrollable = (name: string) =>
  ({
    component: Paper,
    variant: 'outlined',
    tabIndex: 0,
    role: 'region',
    'aria-label': `${name} table`,
    sx: { '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 } },
  }) as const

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Box component="section" aria-label={title} sx={{ mt: 4 }}>
      {/* tabIndex -1: where focus goes when the control that had it is gone. */}
      <Typography component="h2" variant="h6" tabIndex={-1} gutterBottom>
        {title}
      </Typography>
      <Stack spacing={2}>{children}</Stack>
    </Box>
  )
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'max-content 1fr' }, columnGap: 3, rowGap: 1, m: 0 }}>
      {rows.map(([label, value]) => (
        <Box key={label} sx={{ display: 'contents' }}>
          <Typography component="dt" sx={{ fontWeight: 'bold' }}>
            {label}
          </Typography>
          <Typography component="dd" sx={{ m: 0, overflowWrap: 'anywhere' }}>
            {value}
          </Typography>
        </Box>
      ))}
    </Box>
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
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{date(r.created_at)}</TableCell>
              {isEnded && (
                <TableCell>
                  {r.ended_at && date(r.ended_at)}: {r.end_reason}
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
