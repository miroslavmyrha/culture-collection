import { type MouseEvent, useId } from 'react'
import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'
import { StaleNotice } from '@/components/StaleNotice'
import { ActionMenu, type ActionItem, Box, Button, CheckboxField, Mono, SelectField, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { useFocusReturnOnUnmount } from '@/lib/focus'
import { VIAL_TONES } from '@/lib/tones'
import type { useBatches, useVialPage } from '../api/queries'
import { type Batch, nextStates, OUT_OF_A_BOX, type Vial, type VialPage, VIAL_STATUS_LABELS } from '../schemas'
import { type Open, type Show, type ShowFrom } from './materialOpen'
import { MaterialSection } from './MaterialSection'
import { scrollable } from './scroll'
import type { VialSelection } from './useVialSelection'
import { VialPlace } from './VialPlace'

type Props = {
  labId: string
  vials: ReturnType<typeof useVialPage>
  batches: ReturnType<typeof useBatches>
  vialPage: VialPage
  onVialPage: (next: Partial<VialPage>) => void
  selection: VialSelection
  /** How often this page moved each vial: a revealed location starts again when its vial moved. */
  moves: Readonly<Record<string, number>>
  canHandle: boolean
  materialDestroyed: boolean
  canReportLoss: boolean
  show: Show
  showFrom: ShowFrom
}

/** The strain's vials, a page at a time, with the bench work in each row. */
export function VialsSection(props: Props) {
  const { batches, vials, vialPage, onVialPage } = props
  return (
    <MaterialSection title="Vials">
      <BatchFilter batches={batches.data?.results} vialPage={vialPage} onVialPage={onVialPage} />
      {vialPage.vial !== undefined && <OneVial onShowAll={() => onVialPage({ vial: undefined, offset: 0 })} />}
      <StaleNotice what="the vials" query={vials} />
      <VialsBody {...props} />
    </MaterialSection>
  )
}

type FilterProps = { batches: readonly Batch[] | undefined; vialPage: VialPage; onVialPage: (next: Partial<VialPage>) => void }

/** The select that narrows the list to one batch: only when there is more than one to choose. */
function BatchFilter({ batches, vialPage, onVialPage }: FilterProps) {
  if (batches === undefined || batches.length <= 1) return null
  return (
    <Box sx={{ maxWidth: 280 }}>
      <SelectField
        label="Batch"
        value={vialPage.batch ?? ''}
        onChange={(event) => onVialPage({ batch: event.target.value === '' ? undefined : event.target.value, vial: undefined, offset: 0 })}
        options={[{ value: '', label: 'All batches' }, ...batches.map((b) => ({ value: b.public_id, label: `Batch ${b.number}` }))]}
      />
    </Box>
  )
}

/** What the list says when no vial matches what the URL asks for. */
function noVialText(vialPage: VialPage): string {
  if (vialPage.vial) return 'This vial is not one of this strain.'
  return vialPage.batch ? 'No vial in this batch.' : 'No vial yet.'
}

function VialsBody(props: Props) {
  const { vials, vialPage, onVialPage } = props
  if (vials.data === undefined) {
    return vials.isPending ? <Typography>Loading the vials…</Typography> : <LoadError what="the vials" error={vials.error} onRetry={() => void vials.refetch()} />
  }
  if (vials.data.count === 0) return <Typography>{noVialText(vialPage)}</Typography>
  if (vials.data.results.length === 0) return <PastTheEnd onFirstPage={() => onVialPage({ offset: 0 })} />
  return <VialsPage {...props} page={vials.data} />
}

type PageProps = Props & { page: NonNullable<Props['vials']['data']> }

function VialsPage({ page, vials, batches, vialPage, onVialPage, selection, moves, canHandle, materialDestroyed, canReportLoss, show, showFrom, labId }: PageProps) {
  const { loose, selected } = selection
  return (
    <>
      {/* The count of every vial asked for, so a page never hides the rest (#72). */}
      <Typography>{vialCount(page.count, vialPage, batches.data?.results)}</Typography>
      {loose.length > 0 && (
        <PlaceSeveral
          loose={loose.length}
          selected={selected.length}
          onAll={selection.setAll}
          onPlace={(event) => {
            if (selected.length === 0) return
            show({ kind: 'place-many', vials: selected, open: true })(event)
          }}
        />
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
            {page.results.map((v) => (
              <VialRow
                key={v.public_id}
                vial={v}
                labId={labId}
                selection={selection}
                moves={moves[v.public_id] ?? 0}
                canHandle={canHandle}
                materialDestroyed={materialDestroyed}
                canReportLoss={canReportLoss}
                showFrom={showFrom}
              />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Pager
        label="Pages of the vials"
        count={page.count}
        shown={page.results.length}
        limit={vialPage.limit}
        offset={vialPage.offset}
        loading={vials.isPlaceholderData}
        onOffsetChange={(offset) => onVialPage({ offset })}
      />
    </>
  )
}

type RowProps = {
  vial: Vial
  labId: string
  selection: VialSelection
  /** How often this page moved the vial. */
  moves: number
  canHandle: boolean
  materialDestroyed: boolean
  canReportLoss: boolean
  showFrom: ShowFrom
}

/** One vial: its label (a checkbox while it can go into a box), state, place and actions. */
function VialRow({ vial: v, labId, selection, moves, canHandle, materialDestroyed, canReportLoss, showFrom }: RowProps) {
  return (
    <TableRow>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>
        {selection.placeable(v) ? (
          <CheckboxField label={v.label} checked={selection.chosen.has(v.public_id)} onChange={() => selection.toggle(v.public_id)} sx={{ py: 0 }} />
        ) : (
          <Mono>{v.label}</Mono>
        )}
      </TableCell>
      <TableCell>
        <StatusChip tone={VIAL_TONES[v.status]}>{VIAL_STATUS_LABELS[v.status]}</StatusChip>
        {v.police_report && <PoliceReport report={v.police_report} />}
      </TableCell>
      {/* Wide enough to read a path at 320 px: the table scrolls, the row stays short. */}
      <TableCell sx={{ minWidth: 200 }}>
        <VialPlace key={`${v.status_changed_at ?? ''}:${moves}`} labId={labId} vial={v} />
      </TableCell>
      {canHandle && (
        <TableCell>
          <Actions vial={v} materialDestroyed={materialDestroyed} canReportLoss={canReportLoss} show={showFrom} />
        </TableCell>
      )}
    </TableRow>
  )
}

/** The loss of a VRAT or RAT vial and whether the police were told (#159, act 281/2002 Sb., § 5(5)). */
function PoliceReport({ report }: { report: NonNullable<Vial['police_report']> }) {
  return (
    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
      {report.reported_on === null ? 'Not reported to the police yet' : `Reported to the police on ${report.reported_on}, reference ${report.reference ?? ''}`}
    </Typography>
  )
}

/**
 * The list narrowed to the vial a search opened (#76). Show every vial removes this line and its
 * focused button: focus goes to the Vials heading.
 */
function OneVial({ onShowAll }: { onShowAll: () => void }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: 2, rowGap: 1 }}>
      <Typography>Only the vial you searched for.</Typography>
      <Button
        variant="outlined"
        size="small"
        onClick={(event) => {
          remember(event.currentTarget)
          onShowAll()
        }}
      >
        Show every vial
      </Button>
    </Box>
  )
}

type PlaceSeveralProps = {
  /** Vials in no box on this page. */
  loose: number
  selected: number
  onAll: (all: boolean) => void
  onPlace: (event: MouseEvent<HTMLButtonElement>) => void
}

/**
 * Several vials into one box in one step (#77): the vials in no box are chosen in their rows, or
 * all of this page at once. The button stays focusable without a choice and says what it needs.
 */
function PlaceSeveral({ loose, selected, onAll, onPlace }: PlaceSeveralProps) {
  const none = selected === 0
  const hint = useId()
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: 2, rowGap: 1 }}>
      <CheckboxField label={`Every vial in no box on this page (${loose})`} checked={selected === loose} onChange={(event) => onAll(event.target.checked)} />
      <Button variant="outlined" aria-disabled={none} aria-describedby={none ? hint : undefined} onClick={onPlace} sx={{ '&[aria-disabled="true"]': { color: 'text.disabled', cursor: 'not-allowed' } }}>
        {none ? 'Place in a box' : `Place ${selected} ${selected === 1 ? 'vial' : 'vials'} in a box`}
      </Button>
      {none && (
        <Typography id={hint} variant="body2" color="text.secondary">
          Choose the vials in no box first.
        </Typography>
      )}
    </Box>
  )
}

type ActionsProps = {
  vial: Vial
  materialDestroyed: boolean
  canReportLoss: boolean
  show: ShowFrom
}

/**
 * A vial's bench work in one menu per row (#19): move or place, change its state, revive it; for
 * a manager, record the police report of a loss that owes one (#159).
 */
function Actions({ vial, materialDestroyed, canReportLoss, show }: ActionsProps) {
  const items: ActionItem[] = []
  const add = (label: string, kind: Extract<NonNullable<Open>, { vial: Vial }>['kind']) => items.push({ label, onSelect: show({ kind, vial, open: true }) })
  if (!OUT_OF_A_BOX.includes(vial.status)) add(vial.placed ? 'Move' : 'Place', 'place')
  if (nextStates(vial, materialDestroyed).length > 0) add('Change state', 'status')
  if (vial.status === 'available') add('Revive', 'revive')
  if (canReportLoss && vial.police_report?.reported_on === null) add('Record the police report', 'loss-report')
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
