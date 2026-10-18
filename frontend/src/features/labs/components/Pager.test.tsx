import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Pager } from './Pager'

type Props = Parameters<typeof Pager>[0]

function pager(overrides: Partial<Props> = {}) {
  const onOffsetChange = vi.fn<(offset: number) => void>()
  const props: Props = { label: 'Lab pages', count: 60, shown: 25, limit: 25, offset: 25, loading: false, onOffsetChange, ...overrides }
  const view = render(<Pager {...props} />)
  return { ...view, props, onOffsetChange }
}

describe('Pager', () => {
  it('asks for the previous and the next offset', async () => {
    const { onOffsetChange } = pager()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Previous' }))
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(onOffsetChange.mock.calls).toEqual([[0], [50]])
  })

  // Pressing Next on the last but one page: the next render has no next page, and a disabled
  // button would drop the focus to the body.
  it('keeps the focus on Next when it stops having a next page, and ignores presses then', async () => {
    const { rerender, props, onOffsetChange } = pager()
    const user = userEvent.setup()
    const next = screen.getByRole('button', { name: 'Next' })
    await user.click(next)
    rerender(<Pager {...props} offset={50} shown={10} loading />)
    expect(next).toHaveFocus()
    rerender(<Pager {...props} offset={50} shown={10} />)
    expect(next).toHaveFocus()
    expect(next).not.toBeDisabled()
    expect(next).toHaveAttribute('aria-disabled', 'true')
    await user.keyboard('{Enter}')
    await user.click(next)
    expect(onOffsetChange.mock.calls).toEqual([[50]])
  })

  it('ignores both buttons while the next page loads, still focusable', async () => {
    const { onOffsetChange } = pager({ loading: true })
    const user = userEvent.setup()
    for (const name of ['Previous', 'Next']) {
      const button = screen.getByRole('button', { name })
      expect(button).toHaveAttribute('aria-disabled', 'true')
      expect(button).not.toBeDisabled()
      await user.click(button)
    }
    expect(onOffsetChange).not.toHaveBeenCalled()
  })

  it('marks Previous on the first page, and nothing when everything fits', () => {
    const { unmount } = pager({ offset: 0 })
    expect(screen.getByRole('button', { name: 'Previous' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('button', { name: 'Next' })).toHaveAttribute('aria-disabled', 'false')
    unmount()
    pager({ count: 20, offset: 0, shown: 20 })
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })
})
