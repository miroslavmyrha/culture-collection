import { type MouseEvent, useRef, useState } from 'react'
import { type FocusReturn, focusTarget, rememberFocus } from '@/lib/focus'
import { type Growth } from '@/lib/growth'
import { batchVialsPage, useBatches, useBoxes, usePassages, useVialPage } from '../api/queries'
import type { VialPage } from '../schemas'
import { BatchesSection } from './BatchesSection'
import { Destructions } from './Destructions'
import { CheckPanelDialogs, PassageDialogs, VialActionDialogs } from './MaterialDialogs'
import { type InPanel, type Open, type Show, type ShowFrom } from './materialOpen'
import { MaterialSection } from './MaterialSection'
import { PassagesSection } from './PassagesSection'
import { useVialSelection } from './useVialSelection'
import { VialsSection } from './VialsSection'

type Props = {
  labId: string
  strainId: string
  accession: string
  /** The strain's own growth conditions: a revival or a subculture starts from them (#79). */
  strainGrowth: Growth | undefined
  canHandle: boolean
  canRelease: boolean
  /** The strain was deaccessioned with its material destroyed (#150): its vials go only to destruction. */
  materialDestroyed: boolean
  /** The strain's active restriction kinds, undefined until it loaded: what its destruction record asks (#160). */
  restrictionKinds: readonly string[] | undefined
  /** Managers confirm a regulated strain's destruction (#160). */
  canConfirmDestruction: boolean
  /** The strain is a VRAT or RAT: a loss is reported to the police (act 281/2002 Sb., § 5(5), #159). */
  lossReported: boolean
  /** Managers record that a loss was reported (#159). */
  canReportLoss: boolean
  /** The page of the vials the URL holds, and how to ask for another (#72). */
  vialPage: VialPage
  onVialPage: (next: Partial<VialPage>) => void
}

/**
 * A strain's material (ADR 0008, D1), the strain page's Material tab (#19): its passages as a
 * tree from the deposit, its batches and their vials, with the bench work for technicians and up. Where a vial is shows for strains without restrictions;
 * a regulated strain's places are masked, and only a holder of the lab's location grant
 * reveals one (ADR 0009). A batch's checks open in its row (D16): technicians record them,
 * curators release and hold. Vials in no box are selected in their rows and placed into one box
 * in one step (#77). Vials marked to destroy are destroyed only with a destruction record (#160).
 */
export function StrainMaterial({
  labId,
  strainId,
  accession,
  strainGrowth,
  canHandle,
  canRelease,
  materialDestroyed,
  restrictionKinds,
  canConfirmDestruction,
  lossReported,
  canReportLoss,
  vialPage,
  onVialPage,
}: Props) {
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
  const selection = useVialSelection(vials.data?.results, canHandle)
  const spot = useRef<FocusReturn | null>(null)
  const show: Show = (next) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen(next)
  }
  // From a row's menu: the focus goes back to the menu button.
  const showFrom: ShowFrom = (next) => (button) => {
    spot.current = rememberFocus(button)
    setOpen(next)
  }
  // The vials a check of the open batch may name: that batch's, all of them (#72), loaded with the dialog.
  const checked = checkedBatch(open)
  const batchVials = useVialPage(labId, strainId, batchVialsPage(checked ?? ''), checked !== undefined)
  // A control in a panel that the action removes (Release once released) gives the focus to the panel's heading.
  const inPanel: InPanel = (headingId, next) => (event) => {
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
  // Undefined while they load or when they failed: the dialogs mount their box select only once
  // the options exist, and say so when the load failed (an empty list would read as no boxes).
  // A failed refresh keeps the boxes already loaded.
  const boxChoice = { boxes: boxes.data, boxesFailed: boxes.isError && boxes.data === undefined }

  return (
    <>
      <PassagesSection passages={passages} subculture={canHandle ? (p) => show({ kind: 'subculture', passage: p, open: true }) : undefined} />
      <BatchesSection
        labId={labId}
        strainId={strainId}
        batches={batches}
        hasPassages={Boolean(passages.data?.results.length)}
        canHandle={canHandle}
        canRelease={canRelease}
        show={show}
        inPanel={inPanel}
      />
      <VialsSection
        labId={labId}
        vials={vials}
        batches={batches}
        vialPage={vialPage}
        onVialPage={onVialPage}
        selection={selection}
        moves={moves}
        canHandle={canHandle}
        materialDestroyed={materialDestroyed}
        canReportLoss={canReportLoss}
        show={show}
        showFrom={showFrom}
      />
      <MaterialSection title="Destruction">
        <Destructions labId={labId} strainId={strainId} accession={accession} kinds={restrictionKinds} canHandle={canHandle} canConfirm={canConfirmDestruction} />
      </MaterialSection>

      {/* Mounted until they have faded out, so onExited can place the focus; outside the
          lists' loading and error branches, which a write passes through. */}
      <PassageDialogs open={open} common={common} accession={accession} passages={passages.data?.results ?? []} strainGrowth={strainGrowth} {...boxChoice} />
      <VialActionDialogs
        open={open}
        common={common}
        strainGrowth={strainGrowth}
        materialDestroyed={materialDestroyed}
        lossReported={lossReported}
        onMoved={(vial) => moved(vial.public_id)}
        onPlacedMany={selection.clear}
        {...boxChoice}
      />
      <CheckPanelDialogs open={open} common={common} batchVials={batchVials} />
    </>
  )
}

/** The batch whose check dialog is open: its vials load with the dialog. */
function checkedBatch(open: Open): string | undefined {
  return open?.kind === 'check' ? open.batch.public_id : undefined
}
