import { zodResolver } from '@hookform/resolvers/zod'
import { type ReactNode, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { LoadError } from '@/components/LoadError'
import { Box, Button, type GridCell, gridLabel, Link, PositionGrid, type PositionGridHandle, Stack, TextField, Typography } from '@/components/ui'
import type { GridPos } from '@/lib/grid'
import { samePos } from '@/lib/grid'
import { useFindVial, useGridPlace } from '../api/mutations'
import { useBoxGrid } from '../api/queries'
import { type BoxPosition, type FindForm, findSchema, OUT_OF_A_BOX, VIAL_STATUS_LABELS } from '../schemas'
import { gridError, POSITION_TAKEN, vialError } from '../vialErrors'

type Props = {
  labId: string
  boxId: string
  boxName: string
  /** Technicians and up, in a box that takes vials: place and move. Otherwise read only. */
  canHandle: boolean
}

/** The vial on its way: picked in the grid (`from`), or found by its code (`from` null). */
type Moving = { vialId: string; label: string; from: GridPos | null; verb: 'moved' | 'placed' }

const keyOf = (row: number, col: number) => `${row}:${col}`
const MASKED = 'occupied, regulated'

/**
 * What a box holds, as a grid of its positions (ADR 0008, D6), with the bench work for
 * technicians and up: a vial is moved in two steps, select it (Enter, Space or a click), then
 * Enter or a click on an empty position places it there; Escape cancels. A vial scanned or typed
 * into "Vial label or barcode" is placed the same way. One polite status line says what
 * happened, and focus stays on the position the vial went to.
 *
 * A position of a regulated strain's vial says only that it is taken (ADR 0009): the API sends
 * no vial for it, so nothing here can name it. It cannot be picked here; its strain page moves it.
 */
export function BoxPositions({ labId, boxId, boxName, canHandle }: Props) {
  const grid = useBoxGrid(labId, boxId)
  const place = useGridPlace(labId)
  const find = useFindVial(labId)
  const gridRef = useRef<PositionGridHandle>(null)
  const [moving, setMoving] = useState<Moving | null>(null)
  const [message, setMessage] = useState('')
  const [active, setActive] = useState<GridPos>({ row: 0, col: 0 })
  const form = useForm<FindForm>({ resolver: zodResolver(findSchema), defaultValues: { code: '' } })

  const positions = grid.data?.positions ?? []
  const taken = new Map(positions.map((p) => [keyOf(p.row, p.col), p]))
  const at = (pos: GridPos) => taken.get(keyOf(pos.row + 1, pos.col + 1))
  const rows = grid.data?.rows ?? 0
  const cols = grid.data?.cols ?? 0

  function cancel() {
    if (moving === null) return
    setMoving(null)
    setMessage('Move cancelled.')
    if (moving.from) gridRef.current?.focus(moving.from)
    else form.setFocus('code')
  }

  function activate(pos: GridPos) {
    if (place.isPending) return
    const here = gridLabel(pos)
    const position = at(pos)
    if (moving === null) {
      if (!position) return
      if (!position.vial) {
        setMessage(`${here} holds a vial of a regulated strain. Move it from its strain page.`)
        return
      }
      setMoving({ vialId: position.vial.public_id, label: position.vial.label, from: pos, verb: 'moved' })
      setMessage(`${position.vial.label} in ${here} selected. Choose an empty position and press Enter, or Escape to cancel.`)
      return
    }
    if (samePos(moving.from, pos)) {
      cancel()
      return
    }
    if (position) {
      setMessage(POSITION_TAKEN)
      return
    }
    const vial = moving
    place.mutate(
      { vialId: vial.vialId, box: boxId, row: pos.row + 1, col: pos.col + 1 },
      {
        onSuccess: (placed) => {
          setMoving(null)
          // A regulated vial's place is not kept on screen (ADR 0009): the position shows only as taken.
          setMessage(placed.location_masked ? `${vial.label} ${vial.verb}. Its position is hidden: the strain is regulated.` : `${vial.label} ${vial.verb === 'moved' ? 'moved to' : 'placed in'} ${here}.`)
        },
        onError: (error) => setMessage(gridError(error)),
      },
    )
  }

  const refuse = (text: string) => form.setError('code', { type: 'server', message: text }, { shouldFocus: true })

  function findVial({ code }: FindForm) {
    if (find.isPending || place.isPending) return
    find.mutate(code.trim(), {
      onSuccess: ({ results }) => {
        const [vial, other] = results
        if (vial === undefined) return refuse('No vial of this lab has this label or barcode.')
        if (other !== undefined) return refuse('More than one vial has this code. Type the label instead.')
        if (OUT_OF_A_BOX.includes(vial.status)) return refuse('This vial has left the collection or is lost: it has no place.')
        const free = firstFree(rows, cols, at)
        if (free === null) return refuse('This box is full.')
        const inThisBox = positions.find((p) => p.vial?.public_id === vial.public_id)
        form.reset()
        setMoving({
          vialId: vial.public_id,
          label: vial.label,
          from: inThisBox ? { row: inThisBox.row - 1, col: inThisBox.col - 1 } : null,
          verb: vial.placed ? 'moved' : 'placed',
        })
        setMessage(`${vial.label} found. Choose an empty position and press Enter, or Escape to cancel.`)
        gridRef.current?.focus(free)
      },
      onError: (error) => refuse(vialError(error)),
    })
  }

  function cell(pos: GridPos): GridCell {
    const here = gridLabel(pos)
    const position = at(pos)
    const source = moving !== null && samePos(moving.from, pos)
    if (!position) return { name: `${here}, empty`, tone: 'empty', selected: false }
    // Picking needs a vial to pick; a target must be empty. aria-disabled says which would be refused.
    const refused = canHandle && (moving === null ? !position.vial : !source)
    if (!position.vial) return { name: `${here}, ${MASKED}`, tone: 'masked', content: 'Hidden', disabled: refused }
    const v = position.vial
    const state = VIAL_STATUS_LABELS[v.status].toLowerCase()
    return {
      name: `${here}, ${v.label}, ${state}`,
      tone: 'taken',
      selected: source,
      disabled: refused,
      content: (
        <>
          <Line strong>{v.accession_number}</Line>
          <Line>{v.label.split(' / ').slice(-2).join(' / ')}</Line>
          {v.status !== 'available' && <Line>{state}</Line>}
        </>
      ),
    }
  }

  return (
    <Box component="section" aria-label="Positions" sx={{ mt: 4 }}>
      {/* tabIndex -1: where focus goes when the control that had it is gone. */}
      <Typography component="h2" variant="h6" tabIndex={-1} gutterBottom>
        Positions
      </Typography>
      <Stack spacing={2}>
        {canHandle && (
          <Stack component="form" onSubmit={(event) => void form.handleSubmit(findVial)(event)} noValidate aria-label="Place a vial" direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <TextField
              label="Vial label or barcode"
              hint="Scan the tube, or type its label."
              autoComplete="off"
              size="small"
              error={form.formState.errors.code?.message}
              {...form.register('code')}
            />
            <Button type="submit" variant="outlined" aria-disabled={find.isPending} sx={{ '&[aria-disabled="true"]': { color: 'text.disabled', cursor: 'progress' } }}>
              Find
            </Button>
          </Stack>
        )}
        <Typography>
          {canHandle
            ? 'Arrow keys move between positions. Enter, Space or a click picks a vial, then the same on an empty position puts it there. Escape cancels.'
            : 'Arrow keys move between positions.'}
        </Typography>
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center', minHeight: '2.25rem' }}>
          {/* The one live region of the grid (output is role status, polite): selection, results, refusals. */}
          <Typography component="output" sx={{ display: 'block', overflowWrap: 'anywhere' }}>
            {message}
          </Typography>
          {moving && (
            <Button size="small" variant="outlined" onClick={cancel}>
              Cancel move
            </Button>
          )}
        </Stack>
        {grid.isPending ? (
          <Typography>Loading the positions…</Typography>
        ) : grid.isError ? (
          <LoadError what="the positions" error={grid.error} onRetry={() => void grid.refetch()} />
        ) : (
          <>
            <PositionGrid
              ref={gridRef}
              label={`Positions of ${boxName}`}
              rows={rows}
              cols={cols}
              cell={cell}
              onActivate={canHandle ? activate : undefined}
              onEscape={canHandle ? cancel : undefined}
              onActiveChange={setActive}
            />
            <Details labId={labId} here={gridLabel(active)} position={at(active)} />
          </>
        )}
      </Stack>
    </Box>
  )
}

/** The first empty position in fill order, row by row (A1, A2, ..., B1), or null when full. */
function firstFree(rows: number, cols: number, at: (pos: GridPos) => BoxPosition | undefined): GridPos | null {
  for (let row = 0; row < rows; row++) for (let col = 0; col < cols; col++) if (!at({ row, col })) return { row, col }
  return null
}

/** The position that holds the grid's tab stop, in words, with a link to the vial's strain. */
function Details({ labId, here, position }: { labId: string; here: string; position: BoxPosition | undefined }) {
  if (!position) return <Typography>Position {here}: empty.</Typography>
  const v = position.vial
  if (!v) return <Typography>Position {here}: a vial of a regulated strain. Which one is hidden.</Typography>
  return (
    <Typography sx={{ overflowWrap: 'anywhere' }}>
      Position {here}: {v.label}, {VIAL_STATUS_LABELS[v.status].toLowerCase()}.{' '}
      <Link to="/labs/$labId/strains/$strainId" params={{ labId, strainId: v.strain }}>
        Strain {v.accession_number}
      </Link>
    </Typography>
  )
}

function Line({ children, strong = false }: { children: ReactNode; strong?: boolean }) {
  return (
    <Box component="span" sx={{ display: 'block', fontWeight: strong ? 'bold' : undefined, whiteSpace: 'nowrap' }}>
      {children}
    </Box>
  )
}
