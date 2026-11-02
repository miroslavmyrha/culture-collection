import { type FormEvent, useId, useState } from 'react'
import { Box, Button, ConfirmDialog, type GridCell, gridLabel, Mono, PositionGrid, SelectField, Stack, Typography } from '@/components/ui'
import { ApiError, readProblem } from '@/lib/api'
import type { GridPos } from '@/lib/grid'
import { preferences } from '@/lib/storage'
import { usePlaceMany } from '../api/mutations'
import { useBoxGrid } from '../api/queries'
import type { BoxChoice, BoxPosition, Vial } from '../schemas'
import { entryError, gridError, POSITION_TAKEN } from '../vialErrors'

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

const keyOf = (pos: GridPos) => `${pos.row}:${pos.col}`
const BOXES_FAILED = 'Could not load the boxes. Close this dialog and try again.'

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
  const remembered = preferences.get(lastBoxKey(labId))
  // The remembered box only while it is still a box the forms offer (active, of this lab).
  const boxId = chosen ?? (boxes?.some((b) => b.public_id === remembered) ? (remembered ?? '') : '')
  const box = boxes?.find((b) => b.public_id === boxId)
  const grid = useBoxGrid(labId, boxId, box !== undefined)
  const [picks, setPicks] = useState<ReadonlyMap<string, GridPos>>(new Map())
  const [current, setCurrent] = useState(0)
  const [message, setMessage] = useState('')
  const [failure, setFailure] = useState<string>()
  // A refusal names its vial and the position it was refused at: once the plan moves the vial
  // (a position taken meanwhile, refetched), the refusal no longer describes it.
  const [failed, setFailed] = useState<{ vialId: string; text: string; at: string }>()

  const rows = grid.data?.rows ?? 0
  const cols = grid.data?.cols ?? 0
  const taken = new Map<string, BoxPosition>((grid.data?.positions ?? []).map((p) => [keyOf({ row: p.row - 1, col: p.col - 1 }), p]))
  const plan = planOf(vials, picks, taken, rows, cols)
  const free = rows * cols - taken.size
  const planned = new Map([...plan.entries()].map(([vialId, pos]) => [keyOf(pos), vialId]))
  const currentVial = vials[current] ?? vials[0]

  function chooseBox(id: string) {
    setChosen(id)
    setPicks(new Map())
    setCurrent(0)
    setMessage('')
    setFailure(undefined)
    setFailed(undefined)
  }

  function activate(pos: GridPos) {
    if (place.isPending || currentVial === undefined) return
    const here = gridLabel(pos)
    const holder = taken.get(keyOf(pos))
    if (holder) {
      setMessage(POSITION_TAKEN)
      return
    }
    const other = planned.get(keyOf(pos))
    if (other !== undefined && other !== currentVial.public_id && picks.has(other)) {
      // A position picked for another vial: that vial becomes the one to move.
      const index = vials.findIndex((v) => v.public_id === other)
      setCurrent(index)
      setMessage(`${vials[index]?.label ?? ''} in ${here} chosen. Choose a free position for it.`)
      return
    }
    // A vial that had this position only by fill order moves on to the next free one.
    setPicks((before) => new Map(before).set(currentVial.public_id, pos))
    setFailed(undefined)
    setMessage(`${currentVial.label} goes to ${here}.`)
    setCurrent((current + 1) % vials.length)
  }

  function cell(pos: GridPos): GridCell {
    const here = gridLabel(pos)
    const holder = taken.get(keyOf(pos))
    // Taken, never by what: the same for a regulated vial and any other (ADR 0009).
    if (holder) return { name: `${here}, taken`, tone: 'masked', content: 'Taken', disabled: true }
    const vialId = planned.get(keyOf(pos))
    const vial = vials.find((v) => v.public_id === vialId)
    if (vial) return { name: `${here}, ${vial.label}`, tone: 'taken', content: vial.label.split(' / ').slice(-2).join(' / '), selected: vial === currentVial }
    return { name: `${here}, free`, tone: 'empty', selected: false }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (place.isPending) return
    setFailure(undefined)
    setFailed(undefined)
    if (!box) {
      setFailure('Choose the box.')
      return
    }
    if (plan.size < vials.length) {
      setFailure(`This box has ${free} free ${free === 1 ? 'position' : 'positions'} for ${vials.length} vials. Choose another box.`)
      return
    }
    const placements = vials.map((v) => {
      const pos = plan.get(v.public_id) ?? { row: 0, col: 0 }
      return { vial: v.public_id, row: pos.row + 1, col: pos.col + 1 }
    })
    place.mutate(
      { boxId: box.public_id, placements },
      {
        onSuccess: ({ vials: placed }) => {
          if (!placed.some((v) => v.location_masked)) preferences.set(lastBoxKey(labId), box.public_id)
          onPlaced?.()
          onClose()
        },
        onError: (error) => {
          const refusal = refusalOf(error, vials)
          if (refusal) {
            const at = plan.get(refusal.vial.public_id)
            setFailed({ vialId: refusal.vial.public_id, text: refusal.text, at: at ? keyOf(at) : '' })
            setFailure(`Vial ${refusal.vial.label}: ${refusal.text}`)
          } else setFailure(gridError(error))
          // A position someone took meanwhile shows as taken, and the plan moves around it.
          if (error instanceof ApiError && error.code === 'position_taken') void grid.refetch()
        },
      },
    )
  }

  const count = vials.length
  return (
    <ConfirmDialog
      open={open}
      title={`Place ${count} ${count === 1 ? 'vial' : 'vials'} in a box`}
      description="Choose the box. Each vial goes to the next free position, row by row; to choose another, pick the vial, then a free position on the grid."
      confirmLabel={`Place ${count === 1 ? 'vial' : 'vials'}`}
      form={formId}
      pending={place.isPending}
      error={failure ?? (boxesFailed ? BOXES_FAILED : undefined)}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack spacing={2} sx={{ mt: 2 }}>
        <Box component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Box">
          {boxes ? (
            <SelectField
              label="Box"
              value={boxId}
              // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
              autoFocus
              onChange={(event) => chooseBox(event.target.value)}
              options={[{ value: '', label: 'Choose' }, ...boxes.map((b) => ({ value: b.public_id, label: b.label }))]}
            />
          ) : (
            !boxesFailed && <Typography>Loading the boxes…</Typography>
          )}
        </Box>
        {box && grid.data === undefined && (grid.isError ? <Typography>Could not load the positions of this box. Choose it again or close this dialog.</Typography> : <Typography>Loading the positions…</Typography>)}
        {box && grid.data !== undefined && (
          <>
            <Typography>
              {free} of {rows * cols} positions free.
            </Typography>
            <Box component="ul" aria-label="Where each vial goes" sx={{ m: 0, pl: 3 }}>
              {vials.map((v) => {
                const pos = plan.get(v.public_id)
                const refused = failed?.vialId === v.public_id && failed.at === (pos ? keyOf(pos) : '')
                return (
                  <li key={v.public_id}>
                    <Mono>{v.label}</Mono>: {pos ? gridLabel(pos) : 'no free position'}
                    {picks.has(v.public_id) ? ', chosen' : ''}
                    {refused && (
                      <Typography component="span" color="error" sx={{ display: 'block' }}>
                        {failed.text}
                      </Typography>
                    )}
                  </li>
                )
              })}
            </Box>
            {count > 1 && (
              <SelectField
                label="Vial to place on the grid"
                value={String(current)}
                onChange={(event) => setCurrent(Number(event.target.value))}
                options={vials.map((v, index) => ({ value: String(index), label: v.label }))}
              />
            )}
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center', minHeight: '2rem' }}>
              {/* The one live region of the grid (output is role status, polite). */}
              <Typography component="output" sx={{ display: 'block', overflowWrap: 'anywhere' }}>
                {message}
              </Typography>
              {picks.size > 0 && (
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => {
                    setPicks(new Map())
                    setMessage('Each vial goes to the next free position.')
                  }}
                >
                  Next free positions
                </Button>
              )}
            </Stack>
            <PositionGrid label={`Free positions of ${box.label}`} rows={rows} cols={cols} cell={cell} onActivate={activate} />
          </>
        )}
      </Stack>
    </ConfirmDialog>
  )
}

/**
 * Where each vial goes: a picked position first, the others into the free positions in fill
 * order (row by row), skipping taken and picked ones. A vial without a free position is missing.
 */
export function planOf(vials: readonly Vial[], picks: ReadonlyMap<string, GridPos>, taken: ReadonlyMap<string, unknown>, rows: number, cols: number): Map<string, GridPos> {
  const plan = new Map<string, GridPos>()
  const used = new Set<string>(taken.keys())
  for (const v of vials) {
    const pos = picks.get(v.public_id)
    if (pos && !used.has(keyOf(pos))) {
      plan.set(v.public_id, pos)
      used.add(keyOf(pos))
    }
  }
  let row = 0
  let col = 0
  for (const v of vials) {
    if (plan.has(v.public_id)) continue
    while (row < rows && used.has(keyOf({ row, col }))) {
      col++
      if (col === cols) {
        col = 0
        row++
      }
    }
    if (row >= rows) break
    plan.set(v.public_id, { row, col })
    used.add(keyOf({ row, col }))
  }
  return plan
}

/** The vial a refusal is about, from its `placements.<i>` attr, and what it means. */
function refusalOf(error: unknown, vials: readonly Vial[]): { vial: Vial; text: string } | undefined {
  if (!(error instanceof ApiError)) return undefined
  for (const e of readProblem(error.body)?.errors ?? []) {
    const index = /^placements\.(\d+)(\.|$)/.exec(e.attr ?? '')?.[1]
    const vial = index === undefined ? undefined : vials[Number(index)]
    if (vial) return { vial, text: entryError(e.code || error.code || '') }
  }
  return undefined
}
