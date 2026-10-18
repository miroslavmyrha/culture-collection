import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { rememberFocus, useFocusReturnOnUnmount } from './focus'

function Table({ rows, heading = true }: { rows: string[]; heading?: boolean }) {
  return (
    <main tabIndex={-1}>
      <section>
        {heading && <h2>Members</h2>}
        <table>
          <tbody>
            {rows.map((row) => (
              <tr key={row}>
                <td>{row}</td>
                <td>
                  <button type="button">Change {row}</button>
                  <button type="button">Remove {row}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  )
}

const button = (name: string) => screen.getByRole('button', { name })

describe('rememberFocus', () => {
  it('returns to the control while it is in the document', () => {
    render(<Table rows={['a', 'b', 'c']} />)
    const spot = rememberFocus(button('Remove b'))
    expect(spot.restore()).toBe(button('Remove b'))
    expect(button('Remove b')).toHaveFocus()
    expect(button('Remove b')).not.toHaveAttribute('tabindex')
  })

  it('goes to the control at the same place in the next row once its row is gone', () => {
    const { rerender } = render(<Table rows={['a', 'b', 'c']} />)
    const spot = rememberFocus(button('Remove b'))
    rerender(<Table rows={['a', 'c']} />)
    spot.restore()
    expect(button('Remove c')).toHaveFocus()
  })

  it('goes to the previous row when the row was the last', () => {
    const { rerender } = render(<Table rows={['a', 'b', 'c']} />)
    const spot = rememberFocus(button('Change c'))
    rerender(<Table rows={['a', 'b']} />)
    spot.restore()
    expect(button('Change b')).toHaveFocus()
  })

  it('goes to the section heading when no row is left, as a focus target outside the tab order', () => {
    const { rerender } = render(<Table rows={['a']} />)
    const spot = rememberFocus(button('Remove a'))
    rerender(<Table rows={[]} />)
    spot.restore()
    const heading = screen.getByRole('heading', { name: 'Members' })
    expect(heading).toHaveFocus()
    expect(heading).toHaveAttribute('tabindex', '-1')
  })

  it('falls back to the page h1 when the section went too', () => {
    const { rerender } = render(
      <main tabIndex={-1}>
        <section>
          <h2>Error</h2>
          <button type="button">Try again</button>
        </section>
      </main>,
    )
    const spot = rememberFocus(button('Try again'))
    rerender(
      <main tabIndex={-1}>
        <h1>Home</h1>
      </main>,
    )
    spot.restore()
    expect(screen.getByRole('heading', { name: 'Home' })).toHaveFocus()
  })

  it('looks the heading up when it restores, and falls back to main', () => {
    const { rerender } = render(<Table rows={['a']} heading={false} />)
    const spot = rememberFocus(button('Remove a'))
    rerender(<Table rows={[]} />)
    spot.restore()
    expect(screen.getByRole('heading', { name: 'Members' })).toHaveFocus()
    const again = rememberFocus(screen.getByRole('heading', { name: 'Members' }))
    rerender(<Table rows={[]} heading={false} />)
    again.restore()
    expect(screen.getByRole('main')).toHaveFocus()
  })
})

function Retry({ onDone }: { onDone: () => void }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <button
      type="button"
      onClick={(event) => {
        remember(event.currentTarget)
        onDone()
      }}
    >
      Try again
    </button>
  )
}

function Screen({ other = false }: { other?: boolean }) {
  const [done, setDone] = useState(false)
  return (
    <section>
      <h1>Labs</h1>
      {done ? <p>Loaded</p> : <Retry onDone={() => setDone(true)} />}
      {other && <input aria-label="Elsewhere" />}
    </section>
  )
}

describe('useFocusReturnOnUnmount', () => {
  it('moves the focus to the heading when its control goes with the component', async () => {
    render(<Screen />)
    await userEvent.setup().click(button('Try again'))
    expect(screen.getByText('Loaded')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Labs' })).toHaveFocus()
  })

  it('leaves the focus alone when the component unmounts without its control being used', () => {
    const { unmount } = render(<Screen />)
    button('Try again').focus()
    unmount()
    expect(document.body).toHaveFocus()
  })

  it('leaves the focus where the user put it since', async () => {
    render(<Screen other />)
    const elsewhere = screen.getByRole('textbox', { name: 'Elsewhere' })
    const retry = button('Try again')
    // remembered, then the user moves on before the component goes
    retry.addEventListener('click', () => elsewhere.focus())
    await userEvent.setup().click(retry)
    expect(elsewhere).toHaveFocus()
  })
})
