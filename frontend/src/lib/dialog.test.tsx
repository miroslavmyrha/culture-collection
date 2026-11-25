import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { useDialogSlot } from './dialog'

type Slot = { name: string; open: boolean }

/** A list whose rows open a dialog; Remove takes the row away, as a removal does. */
function Rows() {
  const [rows, setRows] = useState(['alpha', 'beta'])
  const { slot, openFrom, close, exited } = useDialogSlot<Slot>()
  return (
    <section>
      <h2>Rows</h2>
      <table>
        <tbody>
          {rows.map((name) => (
            <tr key={name}>
              <td>
                <button type="button" onClick={(event) => openFrom(event.currentTarget, { name, open: true })}>
                  Open {name}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {slot && (
        <dialog open aria-label={`Dialog of ${slot.name}`} data-open={slot.open}>
          <button type="button" onClick={close}>
            Close
          </button>
          <button type="button" onClick={() => setRows((all) => all.filter((r) => r !== slot.name))}>
            Remove
          </button>
          <button type="button" onClick={exited}>
            Faded
          </button>
        </dialog>
      )}
    </section>
  )
}

describe('useDialogSlot', () => {
  it('opens with its value, keeps it while closing, and gives the focus back to the trigger', async () => {
    const user = userEvent.setup()
    render(<Rows />)
    await user.click(screen.getByRole('button', { name: 'Open beta' }))
    const dialog = screen.getByRole('dialog', { name: 'Dialog of beta' })
    expect(dialog).toHaveAttribute('data-open', 'true')
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.getByRole('dialog', { name: 'Dialog of beta' })).toHaveAttribute('data-open', 'false')
    await user.click(screen.getByRole('button', { name: 'Faded' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open beta' })).toHaveFocus()
  })

  it('moves the focus to the next control at the same place when the trigger is gone', async () => {
    const user = userEvent.setup()
    render(<Rows />)
    await user.click(screen.getByRole('button', { name: 'Open alpha' }))
    await user.click(screen.getByRole('button', { name: 'Remove' }))
    await user.click(screen.getByRole('button', { name: 'Faded' }))
    expect(screen.getByRole('button', { name: 'Open beta' })).toHaveFocus()
  })
})
