import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createRef, type Ref, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { GridPos } from '@/lib/grid'
import { type GridCell, gridLabel, PositionGrid, type PositionGridHandle } from './PositionGrid'

const TAKEN: Record<string, string> = { B3: 'MYC 42 / 1 / 1', B4: 'MYC 42 / 1 / 2' }

function cellOf(pos: GridPos, selected: string | null): GridCell {
  const at = gridLabel(pos)
  const vial = TAKEN[at]
  if (at === 'C4') return { name: 'C4, occupied, regulated', tone: 'masked', content: 'Hidden', selected: false }
  if (vial) return { name: `${at}, ${vial}, available`, tone: 'taken', content: vial, selected: at === selected }
  return { name: `${at}, empty`, tone: 'empty', selected: false }
}

/** A grid that selects the position it is given: the selection lives in the parent, as in the app. */
function Selecting({ onActivate, onEscape, handle }: { onActivate?: (pos: GridPos) => void; onEscape?: () => void; handle?: Ref<PositionGridHandle> }) {
  const [selected, setSelected] = useState<string | null>(null)
  return (
    <>
      <button type="button">Before</button>
      <PositionGrid
        ref={handle}
        label="Box 1"
        rows={9}
        cols={9}
        cell={(pos) => cellOf(pos, selected)}
        onActivate={(pos) => {
          setSelected(gridLabel(pos))
          onActivate?.(pos)
        }}
        onEscape={onEscape}
      />
      <button type="button">After</button>
    </>
  )
}

const grid = () => screen.getByRole('grid', { name: 'Box 1' })
const cell = (name: string | RegExp) => within(grid()).getByRole('gridcell', { name })
const stops = () => grid().querySelectorAll('[tabindex="0"]')

describe('PositionGrid', () => {
  it('names every position by its label and what it holds, with letters for rows and numbers for columns', () => {
    render(<Selecting />)
    expect(within(grid()).getAllByRole('gridcell')).toHaveLength(81)
    expect(within(grid()).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['1', '2', '3', '4', '5', '6', '7', '8', '9'])
    expect(within(grid()).getAllByRole('rowheader').map((h) => h.textContent)).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I'])
    expect(cell('A1, empty')).toBeInTheDocument()
    expect(cell('B3, MYC 42 / 1 / 1, available')).toHaveTextContent('MYC 42 / 1 / 1')
    expect(cell('C4, occupied, regulated')).toHaveTextContent('Hidden')
    expect(grid()).not.toHaveAttribute('aria-readonly')
  })

  it('is one tab stop: Tab enters on A1, the next Tab leaves, Shift+Tab comes back to the same position', async () => {
    const user = userEvent.setup()
    render(<Selecting />)
    expect(stops()).toHaveLength(1)
    screen.getByRole('button', { name: 'Before' }).focus()
    await user.tab()
    expect(cell('A1, empty')).toHaveFocus()
    await user.keyboard('{ArrowDown}{ArrowRight}')
    expect(cell('B2, empty')).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'After' })).toHaveFocus()
    await user.tab({ shift: true })
    expect(cell('B2, empty')).toHaveFocus()
    expect(stops()).toHaveLength(1)
  })

  it('moves with the arrows, Home, End, Ctrl+Home, Ctrl+End, PageUp and PageDown, and stops at the edges', async () => {
    const user = userEvent.setup()
    render(<Selecting />)
    cell('A1, empty').focus()
    await user.keyboard('{ArrowUp}{ArrowLeft}')
    expect(cell('A1, empty')).toHaveFocus()
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}')
    expect(cell(/^B3,/)).toHaveFocus()
    await user.keyboard('{End}')
    expect(cell('B9, empty')).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(cell('B9, empty')).toHaveFocus() // no wrap to C1
    await user.keyboard('{Home}')
    expect(cell('B1, empty')).toHaveFocus()
    await user.keyboard('{PageDown}')
    expect(cell('I1, empty')).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(cell('I1, empty')).toHaveFocus() // no wrap to A1
    await user.keyboard('{PageUp}')
    expect(cell('A1, empty')).toHaveFocus()
    await user.keyboard('{Control>}{End}{/Control}')
    expect(cell('I9, empty')).toHaveFocus()
    await user.keyboard('{Control>}{Home}{/Control}')
    expect(cell('A1, empty')).toHaveFocus()
    expect(stops()).toHaveLength(1)
  })

  it('stops the page from scrolling under the keys it handles, and only those', () => {
    render(<Selecting />)
    const a1 = cell('A1, empty')
    a1.focus()
    const arrow = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true })
    act(() => {
      a1.dispatchEvent(arrow)
    })
    expect(arrow.defaultPrevented).toBe(true)
    const letter = new KeyboardEvent('keydown', { key: 'x', bubbles: true, cancelable: true })
    act(() => {
      cell('B1, empty').dispatchEvent(letter)
    })
    expect(letter.defaultPrevented).toBe(false)
  })

  it('Enter, Space and a click activate the position, and aria-selected marks only the chosen one, not the focused one', async () => {
    const user = userEvent.setup()
    const onActivate = vi.fn<(pos: GridPos) => void>()
    render(<Selecting onActivate={onActivate} />)
    cell('A1, empty').focus()
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter}')
    expect(onActivate).toHaveBeenLastCalledWith({ row: 1, col: 2 })
    await user.keyboard('{ArrowRight} ')
    expect(onActivate).toHaveBeenLastCalledWith({ row: 1, col: 3 })
    expect(cell(/^B4,/)).toHaveAttribute('aria-selected', 'true')
    expect(cell(/^B3,/)).toHaveAttribute('aria-selected', 'false')
    await user.keyboard('{ArrowLeft}')
    // Focus moved to B3; the selection stayed on B4.
    expect(cell(/^B3,/)).toHaveFocus()
    expect(cell(/^B3,/)).toHaveAttribute('aria-selected', 'false')
    expect(grid().querySelectorAll('[aria-selected="true"]')).toHaveLength(1)
    await user.click(cell('E5, empty'))
    expect(onActivate).toHaveBeenLastCalledWith({ row: 4, col: 4 })
    expect(onActivate).toHaveBeenCalledTimes(3)
  })

  it('a click moves the tab stop to the clicked position', async () => {
    const user = userEvent.setup()
    render(<Selecting />)
    await user.click(cell('D7, empty'))
    expect(cell('D7, empty')).toHaveAttribute('tabindex', '0')
    expect(stops()).toHaveLength(1)
    await user.keyboard('{ArrowUp}')
    expect(cell(/^C7,/)).toHaveFocus()
  })

  it('Escape goes to the parent, which can put the focus on any position', async () => {
    const user = userEvent.setup()
    const handle = createRef<PositionGridHandle>()
    const onEscape = vi.fn<() => void>(() => handle.current?.focus({ row: 1, col: 2 }))
    render(<Selecting onEscape={onEscape} handle={handle} />)
    cell('A1, empty').focus()
    await user.keyboard('{PageDown}{Escape}')
    expect(onEscape).toHaveBeenCalledOnce()
    expect(cell(/^B3,/)).toHaveFocus()
    expect(cell(/^B3,/)).toHaveAttribute('tabindex', '0')
    expect(stops()).toHaveLength(1)
  })

  it('read only: no selection state, no activation, and the arrows still move', async () => {
    const user = userEvent.setup()
    render(<PositionGrid label="Box 1" rows={9} cols={9} cell={(pos) => cellOf(pos, null)} />)
    expect(grid()).toHaveAttribute('aria-readonly', 'true')
    expect(grid().querySelectorAll('[aria-selected]')).toHaveLength(0)
    cell('A1, empty').focus()
    await user.keyboard('{ArrowDown}{ArrowRight}{ArrowRight}{Enter}')
    expect(cell(/^B3,/)).toHaveFocus()
    expect(grid().querySelectorAll('[aria-selected]')).toHaveLength(0)
  })

  it('marks a refused position aria-disabled and keeps it in the arrow order', async () => {
    const user = userEvent.setup()
    render(<PositionGrid label="Box 1" rows={2} cols={2} cell={(pos) => ({ name: `${gridLabel(pos)}, empty`, tone: 'empty', disabled: pos.col === 1 })} onActivate={vi.fn<(pos: GridPos) => void>()} />)
    expect(cell('A2, empty')).toHaveAttribute('aria-disabled', 'true')
    expect(cell('A1, empty')).not.toHaveAttribute('aria-disabled')
    cell('A1, empty').focus()
    await user.keyboard('{ArrowRight}')
    expect(cell('A2, empty')).toHaveFocus()
  })

  it('keeps the tab stop inside a box that became smaller', () => {
    const { rerender } = render(<PositionGrid label="Box 1" rows={9} cols={9} cell={(pos) => cellOf(pos, null)} />)
    act(() => cell('I9, empty').focus())
    rerender(<PositionGrid label="Box 1" rows={2} cols={2} cell={(pos) => cellOf(pos, null)} />)
    expect(cell('B2, empty')).toHaveAttribute('tabindex', '0')
    expect(stops()).toHaveLength(1)
  })
})
