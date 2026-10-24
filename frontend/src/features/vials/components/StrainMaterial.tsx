import { Fragment, type MouseEvent, type ReactNode, useId, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'
import { StaleNotice } from '@/components/StaleNotice'
import { ActionMenu, type ActionItem, Box, Button, Mono, Paper, SelectField, Stack, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { BATCH_TONES, VIAL_TONES } from '@/lib/tones'
import { type FocusReturn, focusTarget, rememberFocus } from '@/lib/focus'
import { batchVialsPage, useBatches, useBoxes, usePassages, useVialPage } from '../api/queries'
import {
  type Batch,
  type BatchCheck,
  BATCH_STATUS_LABELS,
  batchStatusReason,
  locationText,
  METHOD_LABELS,
  nextStates,
  OUT_OF_A_BOX,
  type Passage,
  type PassageNode,
  passageTree,
  PURPOSE_LABELS,
  sourceLabel,
  type Vial,
  type VialPage,
  VIAL_STATUS_LABELS,
} from '../schemas'
import { BatchChecks } from './BatchChecks'
import { BatchDecisionDialog, CheckErrorDialog, RecordCheckDialog } from './CheckDialogs'
import { RevealLocation } from './RevealLocation'
import { PlaceVialDialog, PreserveBatchDialog, ReviveDialog, SubcultureDialog, VialStatusDialog } from './VialDialogs'

type Props = {
  labId: string
  strainId: string
  accession: string
  canHandle: boolean
  canRelease: boolean
  /** The page of the vials the URL holds, and how to ask for another (#72). */
  vialPage: VialPage
  onVialPage: (next: Partial<VialPage>) => void
}

type Open =
  | { kind: 'preserve'; open: boolean }
  | { kind: 'subculture'; passage: Passage; open: boolean }
  | { kind: 'place' | 'status' | 'revive'; vial: Vial; open: boolean }
  | { kind: 'check'; batch: Batch; checks: readonly BatchCheck[] | undefined; open: boolean }
  | { kind: 'release' | 'hold'; batch: Batch; open: boolean }
  | { kind: 'check-error'; check: BatchCheck; open: boolean }
  | null

/**
 * A strain's material (ADR 0008, D1), the strain page's Material tab (#19): its passages as a
 * tree from the deposit, its batches and their vials, with the bench work for technicians and up. Where a vial is shows for strains without restrictions;
 * a regulated strain's places are masked, and only a holder of the lab's location grant
 * reveals one (ADR 0009). A batch's checks open in its row (D16): technicians record them,
 * curators release and hold.
 */
export function StrainMaterial({ labId, strainId, accession, canHandle, canRelease, vialPage, onVialPage }: Props) {
  const passages = usePassages(labId, strainId)
  const batches = useBatches(labId, strainId)
  const vials = useVialPage(labId, strainId, vialPage)
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
  // From a row's menu: the focus goes back to the menu button.
  const showFrom = (next: NonNullable<Open>) => (button: HTMLButtonElement) => {
    spot.current = rememberFocus(button)
    setOpen(next)
  }
  // The vials a check of the open batch may name: that batch's, all of them (#72), loaded with the dialog.
  const checked = open?.kind === 'check' ? open.batch.public_id : undefined
  const batchVials = useVialPage(labId, strainId, batchVialsPage(checked ?? ''), checked !== undefined)
  // The batches whose checks are open. A control in a panel that the action removes (Release
  // once released) gives the focus to the panel's heading.
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set())
  const toggle = (batchId: string) =>
    setOpened((current) => {
      const next = new Set(current)
      if (!next.delete(batchId)) next.add(batchId)
      return next
    })
  const panelId = useId()
  const inPanel = (headingId: string, next: NonNullable<Open>) => (event: MouseEvent<HTMLButtonElement>) => {
    const control = event.currentTarget
    spot.current = {
      restore: () => {
        const heading = document.getElementById(headingId)
        const target = control.isConnected ? control : heading
        if (target === control) control.focus()
        else if (target) focusTarget(target)
        return target
      },
    }
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
          <>
            {passages.data.count > passageRows.length && (
              <Typography>
                The first {passageRows.length} of {passages.data.count} passages.
              </Typography>
            )}
            <Box component="ul" aria-label="Passages from the deposit" sx={{ listStyle: 'none', m: 0, p: 0 }}>
              {passageTree(passageRows).map((node) => (
                <PassageItem key={node.passage.public_id} node={node} passages={passageRows} subculture={canHandle ? (p) => show({ kind: 'subculture', passage: p, open: true }) : undefined} />
              ))}
            </Box>
          </>
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
          <>
            <Typography>{supply(batches.data.results)}</Typography>
            <TableContainer {...scrollable('Batches')} sx={{ ...scrollable('Batches').sx, containerType: 'inline-size' }}>
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
                    <TableCell>Checks</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {batches.data.results.map((b) => {
                    const expanded = opened.has(b.public_id)
                    const panel = `${panelId}-${b.number}`
                    const heading = `${panel}-heading`
                    return (
                      <Fragment key={b.public_id}>
                        <TableRow>
                          <TableCell>{b.number}</TableCell>
                          <TableCell>{b.passage_number}</TableCell>
                          <TableCell>
                            {METHOD_LABELS[b.method]}
                            {b.cryoprotectant && `, ${b.cryoprotectant}`}
                          </TableCell>
                          <TableCell>{PURPOSE_LABELS[b.purpose]}</TableCell>
                          <TableCell sx={{ whiteSpace: 'nowrap' }}>{b.preserved_on}</TableCell>
                          <TableCell sx={{ minWidth: 160 }}>
                            <StatusChip tone={BATCH_TONES[b.status]}>{BATCH_STATUS_LABELS[b.status]}</StatusChip>
                            {b.status !== 'released' && (
                              <Typography component="span" variant="body2" color="text.secondary" sx={{ display: 'block' }}>
                                {batchStatusReason(b)}
                              </Typography>
                            )}
                          </TableCell>
                          <TableCell>
                            {b.vials_available} of {b.vial_count_created}
                          </TableCell>
                          <TableCell>
                            <Button
                              size="small"
                              aria-expanded={expanded}
                              aria-controls={panel}
                              aria-label={`Checks of batch ${b.number}`}
                              onClick={() => toggle(b.public_id)}
                            >
                              Checks
                            </Button>
                          </TableCell>
                        </TableRow>
                        {expanded && (
                          <TableRow>
                            <TableCell colSpan={8} sx={{ p: 0 }}>
                              {/* As wide as the visible part of the table, and kept in view when it scrolls sideways. */}
                              <Box id={panel} sx={{ position: 'sticky', left: 0, width: '100cqi', boxSizing: 'border-box', p: 2 }}>
                                <BatchChecks
                                  labId={labId}
                                  strainId={strainId}
                                  batch={b}
                                  headingId={heading}
                                  canHandle={canHandle}
                                  canRelease={canRelease}
                                  onRecord={(event, checks) => inPanel(heading, { kind: 'check', batch: b, checks, open: true })(event)}
                                  onDecide={(event, decision) => inPanel(heading, { kind: decision, batch: b, open: true })(event)}
                                  onEnterInError={(event, check) => inPanel(heading, { kind: 'check-error', check, open: true })(event)}
                                />
                              </Box>
                            </TableCell>
                          </TableRow>
                        )}
                      </Fragment>
                    )
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          </>
        )}
      </Section>

      <Section title="Vials">
        {batches.data !== undefined && batches.data.results.length > 1 && (
          <Box sx={{ maxWidth: 280 }}>
            <SelectField
              label="Batch"
              value={vialPage.batch ?? ''}
              onChange={(event) => onVialPage({ batch: event.target.value === '' ? undefined : event.target.value, offset: 0 })}
              options={[{ value: '', label: 'All batches' }, ...batches.data.results.map((b) => ({ value: b.public_id, label: `Batch ${b.number}` }))]}
            />
          </Box>
        )}
        <StaleNotice what="the vials" query={vials} />
        {vials.data === undefined ? (
          vials.isPending ? (
            <Typography>Loading the vials…</Typography>
          ) : (
            <LoadError what="the vials" error={vials.error} onRetry={() => void vials.refetch()} />
          )
        ) : vials.data.count === 0 ? (
          <Typography>{vialPage.batch ? 'No vial in this batch.' : 'No vial yet.'}</Typography>
        ) : vials.data.results.length === 0 ? (
          <PastTheEnd onFirstPage={() => onVialPage({ offset: 0 })} />
        ) : (
          <>
            {/* The count of every vial asked for, so a page never hides the rest (#72). */}
            <Typography>{vialCount(vials.data.count, vialPage, batches.data?.results)}</Typography>
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
                      <TableCell sx={{ whiteSpace: 'nowrap' }}>
                        <Mono>{v.label}</Mono>
                      </TableCell>
                      <TableCell>
                        <StatusChip tone={VIAL_TONES[v.status]}>{VIAL_STATUS_LABELS[v.status]}</StatusChip>
                      </TableCell>
                      {/* Wide enough to read a path at 320 px: the table scrolls, the row stays short. */}
                      <TableCell sx={{ minWidth: 200 }}>
                        <Where key={`${v.status_changed_at ?? ''}:${moves[v.public_id] ?? 0}`} labId={labId} vial={v} />
                      </TableCell>
                      {canHandle && (
                        <TableCell>
                          <Actions vial={v} show={showFrom} />
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
            <Pager
              label="Pages of the vials"
              count={vials.data.count}
              shown={vials.data.results.length}
              limit={vialPage.limit}
              offset={vialPage.offset}
              loading={vials.isPlaceholderData}
              onOffsetChange={(offset) => onVialPage({ offset })}
            />
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
      {open?.kind === 'check' && (
        <RecordCheckDialog {...common} batch={open.batch} vials={batchVials.data?.results ?? (batchVials.isError ? [] : undefined)} checks={open.checks} open={open.open} />
      )}
      {(open?.kind === 'release' || open?.kind === 'hold') && <BatchDecisionDialog {...common} batch={open.batch} decision={open.kind} open={open.open} />}
      {open?.kind === 'check-error' && <CheckErrorDialog {...common} check={open.check} open={open.open} />}
    </>
  )
}

type PassageItemProps = {
  node: PassageNode
  passages: readonly Passage[]
  subculture: ((p: Passage) => (event: MouseEvent<HTMLButtonElement>) => void) | undefined
}

/** One passage and, nested under it, the passages grown or revived from it: plain lists, no tree widget. */
function PassageItem({ node, passages, subculture }: PassageItemProps) {
  const p = node.passage
  return (
    <Box component="li" aria-label={`Passage ${p.number}`}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: 1, minHeight: 32 }}>
        <Typography component="span" sx={{ fontWeight: 600 }}>
          Passage {p.number}
        </Typography>
        <Typography component="span" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
          {sourceLabel(p, passages)}
        </Typography>
        {subculture && (
          <Button size="small" aria-label={`Subculture passage ${p.number}`} onClick={subculture(p)}>
            Subculture
          </Button>
        )}
      </Box>
      {node.children.length > 0 && (
        <Box component="ul" aria-label={`Grown from passage ${p.number}`} sx={{ listStyle: 'none', m: 0, pl: { xs: 1.5, sm: 3 }, ml: 1, borderLeft: 1, borderColor: 'divider' }}>
          {node.children.map((child) => (
            <PassageItem key={child.passage.public_id} node={child} passages={passages} subculture={subculture} />
          ))}
        </Box>
      )}
    </Box>
  )
}

/** Can the collection supply the strain now: the vials of its released distribution batches. */
function supply(batches: readonly Batch[]): string {
  const ready = batches.filter((b) => b.vials_distributable > 0)
  const vials = ready.reduce((sum, b) => sum + b.vials_distributable, 0)
  if (vials === 0) return 'Available for distribution: none. No released batch of distribution stock has a vial left.'
  const from = ready.length === 1 ? `batch ${ready[0]?.number ?? ''}` : `batches ${ready.map((b) => b.number).join(', ')}`
  return `Available for distribution: ${vials} ${vials === 1 ? 'vial' : 'vials'}, from released ${from}.`
}

function Where({ labId, vial }: { labId: string; vial: Vial }) {
  if (vial.location) return <>{locationText(vial.location)}</>
  if (vial.location_masked) return vial.can_reveal ? <RevealLocation labId={labId} vial={vial} /> : <>Hidden: regulated strain</>
  return <>{OUT_OF_A_BOX.includes(vial.status) ? 'Left the collection' : 'Not placed'}</>
}

type ActionsProps = { vial: Vial; show: (next: NonNullable<Open>) => (button: HTMLButtonElement) => void }

/** A vial's bench work in one menu per row (#19): move or place, change its state, revive it. */
function Actions({ vial, show }: ActionsProps) {
  const items: ActionItem[] = []
  if (!OUT_OF_A_BOX.includes(vial.status)) items.push({ label: vial.placed ? 'Move' : 'Place', onSelect: show({ kind: 'place', vial, open: true }) })
  if (nextStates(vial).length > 0) items.push({ label: 'Change state', onSelect: show({ kind: 'status', vial, open: true }) })
  if (vial.status === 'available') items.push({ label: 'Revive', onSelect: show({ kind: 'revive', vial, open: true }) })
  if (items.length === 0) return <Typography variant="body2" color="text.secondary">None</Typography>
  return <ActionMenu label="Actions" name={`Actions for vial ${vial.label}`} items={items} size="small" />
}

/** "230 vials", "Vials 51 to 100 of 230", or for one batch "40 vials of batch 3, of 230 in all". */
function vialCount(count: number, page: VialPage, batches: readonly Batch[] | undefined): string {
  const all = `${count} ${count === 1 ? 'vial' : 'vials'}`
  if (!page.batch) return all
  const batch = batches?.find((b) => b.public_id === page.batch)
  const total = batches?.reduce((sum, b) => sum + b.vial_count_created, 0)
  return `${all} of batch ${batch?.number ?? ''}${total === undefined ? '' : `, of ${total} in all`}.`
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
    <Box component="section" aria-label={title} sx={{ mb: 4 }}>
      {/* tabIndex -1: where focus goes when the control that had it is gone. */}
      <Typography component="h2" variant="h6" tabIndex={-1} gutterBottom>
        {title}
      </Typography>
      <Stack spacing={2}>{children}</Stack>
    </Box>
  )
}
