import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GridPos } from '@/lib/grid'
import { type GridCell, gridLabel, PositionGrid } from './PositionGrid'

// Counts every render of a position's MUI TableCell. Test only: the grid itself carries no counter.
const renders = vi.hoisted(() => new Map<string, number>())

vi.mock('@mui/material', async (importOriginal) => {
  const mui = await importOriginal<typeof import('@mui/material')>()
  const Counted = (props: ComponentProps<typeof mui.TableCell>) => {
    const pos: unknown = Reflect.get(props, 'data-pos')
    if (typeof pos === 'string') renders.set(pos, (renders.get(pos) ?? 0) + 1)
    return <mui.TableCell {...props} />
  }
  return { ...mui, TableCell: Counted }
})

const cellOf = (pos: GridPos): GridCell => ({ name: `${gridLabel(pos)}, empty`, tone: 'empty', selected: false })

/** What one key rendered: the positions whose cell rendered since `renders` was last cleared. */
const rendered = () => [...renders.keys()].toSorted()

describe('PositionGrid renders', () => {
  beforeEach(() => renders.clear())

  it('renders only the two cells whose state changed on one arrow key', async () => {
    const user = userEvent.setup()
    // The caller's `cell` and handlers are new on every render of the parent, as in an inline arrow.
    render(<PositionGrid label="Box 1" rows={9} cols={9} cell={(pos) => cellOf(pos)} onActivate={() => undefined} onActiveChange={() => undefined} />)
    expect(renders.size).toBe(81)
    screen.getByRole('gridcell', { name: 'E5, empty' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('gridcell', { name: 'E6, empty' })).toHaveFocus()
    renders.clear()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('gridcell', { name: 'F6, empty' })).toHaveFocus()
    // E6 loses the tab stop, F6 gets it. The other 79 keep their element.
    expect(rendered()).toEqual(['E6', 'F6'])
  })
})
