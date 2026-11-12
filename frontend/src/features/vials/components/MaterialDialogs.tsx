import type { Growth } from '@/lib/growth'
import type { useVialPage } from '../api/queries'
import type { BoxChoice, Passage, Vial } from '../schemas'
import { BatchDecisionDialog, CheckErrorDialog, RecordCheckDialog } from './CheckDialogs'
import type { Open } from './materialOpen'
import { PlaceVialsDialog } from './PlaceVialsDialog'
import { LossReportDialog, PlaceVialDialog, PreserveBatchDialog, ReviveDialog, SubcultureDialog, VialStatusDialog } from './VialDialogs'

/** What every dialog of the tab takes: where it is, and how it closes. */
export type DialogCommon = { labId: string; strainId: string; onClose: () => void; onExited: () => void }

type Boxes = { boxes: readonly BoxChoice[] | undefined; boxesFailed: boolean }

type PassageDialogsProps = {
  open: Open
  common: DialogCommon
  accession: string
  passages: readonly Passage[]
  /** The strain's own growth conditions: a subculture starts from them. */
  strainGrowth: Growth | undefined
} & Boxes

/** The dialogs a passage or the batch list opens: preserve a batch, subculture a passage. */
export function PassageDialogs({ open, common, accession, passages, strainGrowth, boxes, boxesFailed }: PassageDialogsProps) {
  if (open === null) return null
  if (open.kind === 'preserve') return <PreserveBatchDialog {...common} accession={accession} passages={passages} boxes={boxes} boxesFailed={boxesFailed} open={open.open} />
  if (open.kind === 'subculture') return strainGrowth && <SubcultureDialog {...common} passage={open.passage} strainGrowth={strainGrowth} open={open.open} />
  return null
}

type VialDialogsProps = {
  open: Open
  common: DialogCommon
  strainGrowth: Growth | undefined
  materialDestroyed: boolean
  lossReported: boolean
  onMoved: (vial: Vial) => void
  onPlacedMany: () => void
} & Boxes

/** The dialogs a vial's row opens: place, change state, revive, record a loss report, place several. */
export function VialActionDialogs({ open, common, strainGrowth, materialDestroyed, lossReported, boxes, boxesFailed, onMoved, onPlacedMany }: VialDialogsProps) {
  if (open === null) return null
  if (open.kind === 'place') return <PlaceVialDialog {...common} vial={open.vial} boxes={boxes} boxesFailed={boxesFailed} open={open.open} onPlaced={() => onMoved(open.vial)} />
  if (open.kind === 'place-many') return <PlaceVialsDialog {...common} vials={open.vials} boxes={boxes} boxesFailed={boxesFailed} open={open.open} onPlaced={onPlacedMany} />
  if (open.kind === 'status') return <VialStatusDialog {...common} vial={open.vial} materialDestroyed={materialDestroyed} lossReported={lossReported} open={open.open} />
  if (open.kind === 'loss-report') return open.vial.status_changed_at !== null && <LossReportDialog {...common} vial={open.vial} lostAt={open.vial.status_changed_at} open={open.open} />
  if (open.kind === 'revive') return strainGrowth && <ReviveDialog {...common} vial={open.vial} strainGrowth={strainGrowth} open={open.open} />
  return null
}

type CheckDialogsProps = {
  open: Open
  common: DialogCommon
  /** The vials a check of the open batch may name: all of that batch's (#72). */
  batchVials: ReturnType<typeof useVialPage>
}

/** The dialogs a batch's checks panel opens: record a check, release, hold, enter a check in error. */
export function CheckPanelDialogs({ open, common, batchVials }: CheckDialogsProps) {
  if (open === null) return null
  if (open.kind === 'check') return <RecordCheckDialog {...common} batch={open.batch} vials={checkVials(batchVials)} vialsTotal={batchVials.data?.count} checks={open.checks} open={open.open} />
  if (open.kind === 'release' || open.kind === 'hold') return <BatchDecisionDialog {...common} batch={open.batch} decision={open.kind} open={open.open} />
  if (open.kind === 'check-error') return <CheckErrorDialog {...common} check={open.check} open={open.open} />
  return null
}


/** The vials the check dialog lists: none when they failed to load, undefined while they load. */
function checkVials(batchVials: ReturnType<typeof useVialPage>): readonly Vial[] | undefined {
  return batchVials.data?.results ?? (batchVials.isError ? [] : undefined)
}
