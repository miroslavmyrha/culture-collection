import { type MouseEvent, type ReactNode, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useBatches, useBoxes, usePassages, useVials } from '../api/queries'
import {
  BATCH_STATUS_LABELS,
  locationText,
  METHOD_LABELS,
  nextStates,
  OUT_OF_A_BOX,
  type Passage,
  PURPOSE_LABELS,
  sourceLabel,
  type Vial,
  VIAL_STATUS_LABELS,
} from '../schemas'
import { RevealLocation } from './RevealLocation'
import { PlaceVialDialog, PreserveBatchDialog, ReviveDialog, SubcultureDialog, VialStatusDialog } from './VialDialogs'

type Props = { labId: string; strainId: string; accession: string; canHandle: boolean }

type Open =
  | { kind: 'preserve'; open: boolean }
  | { kind: 'subculture'; passage: Passage; open: boolean }
  | { kind: 'place' | 'status' | 'revive'; vial: Vial; open: boolean }
  | null

/**
 * A strain's material (ADR 0008, D1): its passages, its batches and their vials, with the
 * bench work for technicians and up. Where a vial is shows for strains without restrictions;
 * a regulated strain's places are masked, and only a holder of the lab's location grant
 * reveals one (ADR 0009).
 */
export function StrainMaterial({ labId, strainId, accession, canHandle }: Props) {
  const passages = usePassages(labId, strainId)
  const batches = useBatches(labId, strainId)
  const vials = useVials(labId, strainId)
  const [open, setOpen] = useState<Open>(null)
  // How often this page moved each vial. A revealed location answers one request and is wrong
  // once the vial moved, so the vial's location cell starts again (its key changes). A state
  // change, which may take the vial out of its position, changes status_changed_at, also in the key.
  const [moves, setMoves] = useState<Readonly<Record<string, number>>>({})
  const moved = (vialId: string) => setMoves((current) => ({ ...current, [vialId]: (current[vialId] ?? 0) + 1 }))
  const boxes = useBoxes(labId, canHandle)
  const spot = useRef<FocusReturn | null>(null)
  const remember = (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
  }
  const show = (next: NonNullable<Open>) => (event: MouseEvent<HTMLButtonElement>) => {
    remember(event)
    setOpen(next)
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }
  const common = { labId, strainId, onClose: close, onExited: exited }
  const passageRows = passages.data?.results ?? []
  // Undefined while they load: the dialogs mount their box select only once the options exist.
  // A failed refresh keeps the boxes already loaded.
  const boxList = boxes.data ?? (boxes.isError ? [] : undefined)

  return (
    <>
      <Section title="Passages">
        <StaleNotice what="the passages" query={passages} />
        {passages.isPending ? (
          <Typography>Loading the passages…</Typography>
        ) : passages.data === undefined ? (
          <LoadError what="the passages" error={passages.error} onRetry={() => void passages.refetch()} />
        ) : passageRows.length === 0 ? (
          <Typography>No passage yet. A strain gets passage 0 when its deposit is accepted.</Typography>
        ) : (
          <TableContainer {...scrollable('Passages')}>
            <Table aria-label="Passages" size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Passage</TableCell>
                  <TableCell>Source</TableCell>
                  {canHandle && <TableCell>Action</TableCell>}
                </TableRow>
              </TableHead>
              <TableBody>
                {passageRows.map((p) => (
                  <TableRow key={p.public_id}>
                    <TableCell>{p.number}</TableCell>
                    <TableCell>{sourceLabel(p, passageRows)}</TableCell>
                    {canHandle && (
                      <TableCell>
                        <Button size="small" aria-label={`Subculture passage ${p.number}`} onClick={show({ kind: 'subculture', passage: p, open: true })}>
                          Subculture
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Section>

      <Section title="Batches">
        {canHandle && passageRows.length > 0 && (
          <Box>
            <Button variant="outlined" onClick={show({ kind: 'preserve', open: true })}>
              Preserve a batch
            </Button>
          </Box>
        )}
        <StaleNotice what="the batches" query={batches} />
        {batches.isPending ? (
          <Typography>Loading the batches…</Typography>
        ) : batches.data === undefined ? (
          <LoadError what="the batches" error={batches.error} onRetry={() => void batches.refetch()} />
        ) : batches.data.count === 0 ? (
          <Typography>No batch preserved yet.</Typography>
        ) : (
          <TableContainer {...scrollable('Batches')}>
            <Table aria-label="Batches" size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Batch</TableCell>
                  <TableCell>From passage</TableCell>
                  <TableCell>Method</TableCell>
                  <TableCell>Purpose</TableCell>
                  <TableCell>Preserved on</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Vials available</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {batches.data.results.map((b) => (
                  <TableRow key={b.public_id}>
                    <TableCell>{b.number}</TableCell>
                    <TableCell>{b.passage_number}</TableCell>
                    <TableCell>
                      {METHOD_LABELS[b.method]}
                      {b.cryoprotectant && `, ${b.cryoprotectant}`}
                    </TableCell>
                    <TableCell>{PURPOSE_LABELS[b.purpose]}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{b.preserved_on}</TableCell>
                    <TableCell>{BATCH_STATUS_LABELS[b.status]}</TableCell>
                    <TableCell>
                      {b.vials_available} of {b.vial_count_created}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Section>

      <Section title="Vials">
        <StaleNotice what="the vials" query={vials} />
        {vials.isPending ? (
          <Typography>Loading the vials…</Typography>
        ) : vials.data === undefined ? (
          <LoadError what="the vials" error={vials.error} onRetry={() => void vials.refetch()} />
        ) : vials.data.count === 0 ? (
          <Typography>No vial yet.</Typography>
        ) : (
          <>
            {vials.data.count > vials.data.results.length && (
              <Typography>
                The first {vials.data.results.length} of {vials.data.count} vials.
              </Typography>
            )}
            <TableContainer {...scrollable('Vials')}>
              <Table aria-label="Vials" size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Vial</TableCell>
                    <TableCell>State</TableCell>
                    <TableCell>Location</TableCell>
                    {canHandle && <TableCell>Actions</TableCell>}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {vials.data.results.map((v) => (
                    <TableRow key={v.public_id}>
                      <TableCell sx={{ whiteSpace: 'nowrap' }}>{v.label}</TableCell>
                      <TableCell>{VIAL_STATUS_LABELS[v.status]}</TableCell>
                      <TableCell>
                        <Where key={`${v.status_changed_at ?? ''}:${moves[v.public_id] ?? 0}`} labId={labId} vial={v} />
                      </TableCell>
                      {canHandle && (
                        <TableCell>
                          <Actions vial={v} show={show} />
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </>
        )}
      </Section>

      {/* Mounted until they have faded out, so onExited can place the focus; outside the
          lists' loading and error branches, which a write passes through. */}
      {open?.kind === 'preserve' && (
        <PreserveBatchDialog {...common} accession={accession} passages={passageRows} boxes={boxList} open={open.open} />
      )}
      {open?.kind === 'subculture' && <SubcultureDialog {...common} passage={open.passage} open={open.open} />}
      {open?.kind === 'place' && (
        <PlaceVialDialog {...common} vial={open.vial} boxes={boxList} open={open.open} onPlaced={() => moved(open.vial.public_id)} />
      )}
      {open?.kind === 'status' && <VialStatusDialog {...common} vial={open.vial} open={open.open} />}
      {open?.kind === 'revive' && <ReviveDialog {...common} vial={open.vial} open={open.open} />}
    </>
  )
}

function Where({ labId, vial }: { labId: string; vial: Vial }) {
  if (vial.location) return <>{locationText(vial.location)}</>
  if (vial.location_masked) return vial.can_reveal ? <RevealLocation labId={labId} vial={vial} /> : <>Hidden: regulated strain</>
  return <>{OUT_OF_A_BOX.includes(vial.status) ? 'Left the collection' : 'Not placed'}</>
}

type ActionsProps = { vial: Vial; show: (next: NonNullable<Open>) => (event: MouseEvent<HTMLButtonElement>) => void }

function Actions({ vial, show }: ActionsProps) {
  const inABox = !OUT_OF_A_BOX.includes(vial.status)
  const states = nextStates(vial)
  return (
    <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
      {inABox && (
        <Button size="small" aria-label={`${vial.placed ? 'Move' : 'Place'} vial ${vial.label}`} onClick={show({ kind: 'place', vial, open: true })}>
          {vial.placed ? 'Move' : 'Place'}
        </Button>
      )}
      {states.length > 0 && (
        <Button size="small" aria-label={`Change the state of vial ${vial.label}`} onClick={show({ kind: 'status', vial, open: true })}>
          Change state
        </Button>
      )}
      {vial.status === 'available' && (
        <Button size="small" aria-label={`Revive vial ${vial.label}`} onClick={show({ kind: 'revive', vial, open: true })}>
          Revive
        </Button>
      )}
    </Stack>
  )
}

/**
 * A table that may scroll sideways on a narrow screen: a named region and a tab stop, so a
 * keyboard user can scroll it (WCAG 2.1.1; axe scrollable-region-focusable).
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

function Section({ title, children }: { title: string; children: ReactNode }) {
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
