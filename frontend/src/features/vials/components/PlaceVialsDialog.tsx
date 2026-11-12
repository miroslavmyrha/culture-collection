import { type FormEvent, useId, useState } from 'react'
import { Box, ConfirmDialog, Stack } from '@/components/ui'
import { preferences } from '@/lib/storage'
import { usePlaceMany } from '../api/mutations'
import { useBoxGrid } from '../api/queries'
import type { BoxChoice, BoxPosition, Vial } from '../schemas'
import { noRoomText, placementsOf, takenOf } from './placement'
import { BOXES_FAILED, BoxPicker, BoxPlan } from './PlaceVialsParts'
import { usePlaceFailure } from './usePlaceFailure'
import { usePlacementPicks } from './usePlacementPicks'

type Props = {
  labId: string
  strainId: string
  /** The vials to place, all in no box, in the order they go into the free positions. */
  vials: readonly Vial[]
  boxes: readonly BoxChoice[] | undefined
  boxesFailed: boolean
  open: boolean
  onClose: () => void
  onExited: () => void
  /** After the server placed the vials, before the dialog closes. */
  onPlaced?: () => void
}

/**
 * The box the person last placed vials of this lab into (#77): a per-viewer convenience in this
 * browser (lib/storage), so the dialog opens on it. Nothing depends on it: without storage, or
 * when that box is gone or out of service, the dialog asks for a box as before.
 */
export const lastBoxKey = (labId: string) => `vials.last-box.${labId}`

/** The box to start from: the one chosen, else the remembered one while it is still a box the forms offer (active, of this lab). */
function startBox(chosen: string | null, boxes: readonly BoxChoice[] | undefined, remembered: string | null): string {
  if (chosen !== null) return chosen
  return boxes?.some((b) => b.public_id === remembered) ? (remembered ?? '') : ''
}

const NOUNS = ['vials', 'vial']

/** The grid of the chosen box as numbers: its size, the taken positions and how many are free. Nothing while it loads. */
function shapeOf(data: { rows: number; cols: number; positions: readonly BoxPosition[] } | undefined) {
  const rows = data?.rows ?? 0
  const cols = data?.cols ?? 0
  const taken = takenOf(data?.positions)
  return { rows, cols, taken, free: rows * cols - taken.size }
}

/** The box is remembered for next time, unless a vial placed is of a regulated strain. */
function rememberBox(labId: string, boxId: string, placed: readonly Vial[]) {
  if (!placed.some((v) => v.location_masked)) preferences.set(lastBoxKey(labId), boxId)
}

/**
 * Places several vials into one box in one step (#77): the box once, its free positions on a
 * grid, and each vial planned into the next free position in fill order (A1, A2, ..., B1). A
 * person who wants other positions picks a vial, then a free position on the grid (Enter, Space
 * or a click); "Next free positions" drops the picks. One request for all, all or nothing: a
 * refusal names the vial it is about.
 *
 * A taken position says only that it is taken (ADR 0009). The box is remembered for the next
 * time only when no vial placed is of a regulated strain: a dialog never prefills where a
 * regulated vial went.
 */
export function PlaceVialsDialog({ labId, strainId, vials, boxes, boxesFailed, open, onClose, onExited, onPlaced }: Props) {
  const place = usePlaceMany(labId, strainId)
  const formId = useId()
  const [chosen, setChosen] = useState<string | null>(null)
  const boxId = startBox(chosen, boxes, preferences.get(lastBoxKey(labId)))
  const box = boxes?.find((b) => b.public_id === boxId)
  const grid = useBoxGrid(labId, boxId, box !== undefined)
  const fail = usePlaceFailure(vials, () => void grid.refetch())
  const { rows, cols, taken, free } = shapeOf(grid.data)
  const picker = usePlacementPicks({ vials, taken, rows, cols, locked: place.isPending, onPick: fail.dropRefusal })
  const { plan } = picker

  function chooseBox(id: string) {
    setChosen(id)
    picker.reset()
    fail.clear()
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (place.isPending) return
    fail.clear()
    if (!box) return fail.setFailure('Choose the box.')
    if (plan.size < vials.length) return fail.setFailure(noRoomText(free, vials.length))
    place.mutate(
      { boxId: box.public_id, placements: placementsOf(vials, plan) },
      {
        onSuccess: ({ vials: placed }) => {
          rememberBox(labId, box.public_id, placed)
          onPlaced?.()
          onClose()
        },
        onError: (error) => fail.refuse(error, plan),
      },
    )
  }

  const count = vials.length
  const noun = NOUNS[Number(count === 1)]
  return (
    <ConfirmDialog
      open={open}
      title={`Place ${count} ${noun} in a box`}
      description="Choose the box. Each vial goes to the next free position, row by row; to choose another, pick the vial, then a free position on the grid."
      confirmLabel={`Place ${noun}`}
      form={formId}
      pending={place.isPending}
      error={fail.failure ?? (boxesFailed ? BOXES_FAILED : undefined)}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack spacing={2} sx={{ mt: 2 }}>
        <Box component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Box">
          <BoxPicker boxes={boxes} boxesFailed={boxesFailed} boxId={boxId} onChoose={chooseBox} />
        </Box>
        {box && <BoxPlan boxLabel={box.label} grid={grid} free={free} taken={taken} vials={vials} picker={picker} failed={fail.failed} />}
      </Stack>
    </ConfirmDialog>
  )
}
