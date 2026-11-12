import { Box, Button, gridLabel, Mono, PositionGrid, SelectField, Stack, Typography } from '@/components/ui'
import type { GridPos } from '@/lib/grid'
import type { useBoxGrid } from '../api/queries'
import { type BoxChoice, boxOption, type Vial } from '../schemas'
import { cellOf, keyOf } from './placement'
import type { usePlacementPicks } from './usePlacementPicks'

/** The dialog's answer to a box list that did not load. */
export const BOXES_FAILED = 'Could not load the boxes. Close this dialog and try again.'

type PickerProps = { boxes: readonly BoxChoice[] | undefined; boxesFailed: boolean; boxId: string; onChoose: (id: string) => void }

/** The box to place into: the choice, or what stands in its place while the boxes load or when they did not. */
export function BoxPicker({ boxes, boxesFailed, boxId, onChoose }: PickerProps) {
  if (boxes === undefined) return boxesFailed ? null : <Typography>Loading the boxes…</Typography>
  return (
    <SelectField
      label="Box"
      value={boxId}
      // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
      autoFocus
      onChange={(event) => onChoose(event.target.value)}
      options={[{ value: '', label: 'Choose' }, ...boxes.map(boxOption)]}
    />
  )
}

/** What stands in place of the grid until the box's positions are there: a failed load, or the wait. */
export function GridUnavailable({ grid }: { grid: ReturnType<typeof useBoxGrid> }) {
  if (grid.isError) return <Typography>Could not load the positions of this box. Choose it again or close this dialog.</Typography>
  return <Typography>Loading the positions…</Typography>
}

/** A refusal the server named: the vial, what it means, and the position it was refused at. */
export type Refused = { vialId: string; text: string; at: string }

type PlanProps = { vials: readonly Vial[]; plan: ReadonlyMap<string, GridPos>; picks: ReadonlyMap<string, GridPos>; failed: Refused | undefined }

function PlanRow({ vial, pos, chosen, refusal }: { vial: Vial; pos: GridPos | undefined; chosen: boolean; refusal: string | undefined }) {
  return (
    <li>
      <Mono>{vial.label}</Mono>: {pos ? gridLabel(pos) : 'no free position'}
      {chosen ? ', chosen' : ''}
      {refusal !== undefined && (
        <Typography component="span" color="error" sx={{ display: 'block' }}>
          {refusal}
        </Typography>
      )}
    </li>
  )
}

/** Where each vial goes. A refusal shows only while the vial is still at the position it was refused at. */
export function PlanList({ vials, plan, picks, failed }: PlanProps) {
  return (
    <Box component="ul" aria-label="Where each vial goes" sx={{ m: 0, pl: 3 }}>
      {vials.map((v) => {
        const pos = plan.get(v.public_id)
        const refused = failed?.vialId === v.public_id && failed.at === (pos ? keyOf(pos) : '')
        return <PlanRow key={v.public_id} vial={v} pos={pos} chosen={picks.has(v.public_id)} refusal={refused ? failed.text : undefined} />
      })}
    </Box>
  )
}

/** The one live region of the grid (output is role status, polite), and the button that drops the picks. */
export function PicksBar({ message, hasPicks, onDrop }: { message: string; hasPicks: boolean; onDrop: () => void }) {
  return (
    <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center', minHeight: '2rem' }}>
      <Typography component="output" sx={{ display: 'block', overflowWrap: 'anywhere' }}>
        {message}
      </Typography>
      {hasPicks && (
        <Button size="small" variant="outlined" onClick={onDrop}>
          Next free positions
        </Button>
      )}
    </Stack>
  )
}

/** Which vial the next grid choice is for, asked only when there is more than one. */
export function VialSelect({ vials, current, onChoose }: { vials: readonly Vial[]; current: number; onChoose: (index: number) => void }) {
  if (vials.length < 2) return null
  return (
    <SelectField
      label="Vial to place on the grid"
      value={String(current)}
      onChange={(event) => onChoose(Number(event.target.value))}
      options={vials.map((v, index) => ({ value: String(index), label: v.label }))}
    />
  )
}

type BoxPlanProps = {
  boxLabel: string
  grid: ReturnType<typeof useBoxGrid>
  free: number
  taken: ReadonlyMap<string, unknown>
  vials: readonly Vial[]
  picker: ReturnType<typeof usePlacementPicks>
  failed: Refused | undefined
}

/** The chosen box once its positions are there: how many are free, the plan, the picks and the grid. */
export function BoxPlan({ boxLabel, grid, free, taken, vials, picker, failed }: BoxPlanProps) {
  if (grid.data === undefined) return <GridUnavailable grid={grid} />
  const { rows, cols } = grid.data
  return (
    <>
      <Typography>
        {free} of {rows * cols} positions free.
      </Typography>
      <PlanList vials={vials} plan={picker.plan} picks={picker.picks} failed={failed} />
      <VialSelect vials={vials} current={picker.current} onChoose={picker.chooseVial} />
      <PicksBar message={picker.message} hasPicks={picker.picks.size > 0} onDrop={picker.dropPicks} />
      <PositionGrid
        label={`Free positions of ${boxLabel}`}
        rows={rows}
        cols={cols}
        cell={(pos) => cellOf(pos, taken, picker.planned, vials, picker.currentVial)}
        onActivate={picker.activate}
      />
    </>
  )
}
