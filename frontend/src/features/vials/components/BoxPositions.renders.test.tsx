import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeBoxGrid, makeBoxVial, makePosition } from '@/test/factories'
import { mockApi } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { BoxPositions } from './BoxPositions'

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

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const BOX_ID = '00000000-0000-4000-8000-0000000000b1'
const BOX = '/api/v1/labs/{lab_public_id}/boxes/{public_id}/'

const vial = makeBoxVial({ public_id: '00000000-0000-4000-8000-0000000000f1', label: 'MYC 42 / 1 / 1' })
const other = makeBoxVial({ public_id: '00000000-0000-4000-8000-0000000000f2', label: 'MYC 42 / 1 / 2', status: 'quarantined' })
const FULL = makeBoxGrid({ public_id: BOX_ID, positions: [makePosition('B3', vial), makePosition('B4', 'masked'), makePosition('E7', other)] })

describe('BoxPositions renders', { timeout: 20_000 }, () => {
  beforeEach(() => renders.clear())

  // BoxPositions itself renders on every key (it shows the focused position), so its `cell`
  // callback and the vial content it builds must not make every grid cell render again.
  it('renders only the two cells whose state changed on one arrow key, taken cells included', async () => {
    mockApi('get', BOX, FULL)
    const user = userEvent.setup()
    await renderWithProviders(<BoxPositions labId={LAB_ID} boxId={BOX_ID} boxName="Box 1" canHandle />)
    const grid = await screen.findByRole('grid', { name: 'Positions of Box 1' })
    within(grid).getByRole('gridcell', { name: 'B2, empty' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(within(grid).getByRole('gridcell', { name: /^B3,/ })).toHaveFocus()
    renders.clear()
    await user.keyboard('{ArrowRight}')
    expect(within(grid).getByRole('gridcell', { name: /^B4,/ })).toHaveFocus()
    expect([...renders.keys()].toSorted()).toEqual(['B3', 'B4'])
  })
})
