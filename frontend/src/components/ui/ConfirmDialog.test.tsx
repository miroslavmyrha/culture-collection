import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './ConfirmDialog'

type Options = { title?: string; description?: string; destructive?: boolean; pending?: boolean; error?: string }

function setup(options: Options = {}) {
  const onClose = vi.fn<() => void>()
  const onConfirm = vi.fn<() => void>()
  const dialog = (next: Options) => (
    <ConfirmDialog
      open
      title={next.title ?? 'Remove bob?'}
      description={next.description ?? 'bob loses access at once.'}
      confirmLabel="Remove"
      destructive={next.destructive ?? true}
      pending={next.pending ?? false}
      error={next.error}
      onClose={onClose}
      onConfirm={onConfirm}
    />
  )
  const view = render(dialog(options))
  const rerender = (next: Options) => view.rerender(dialog({ ...options, ...next }))
  return { onClose, onConfirm, rerender, user: userEvent.setup() }
}

/** The container around the paper: a click there is a click on the backdrop for MUI. */
const backdropOf = (dialog: HTMLElement) => {
  const container = dialog.parentElement
  if (!container) throw new Error('the dialog has no container')
  return container
}

function FormDialog({ pending, onSubmit }: { pending: boolean; onSubmit: () => void }) {
  return (
    <ConfirmDialog open title="Rename" description="The new name shows at once." confirmLabel="Save" pending={pending} form="rename" onClose={() => {}}>
      <form
        id="rename"
        aria-label="Rename"
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit()
        }}
      />
    </ConfirmDialog>
  )
}

describe('ConfirmDialog', () => {
  it('is an alertdialog named by the title and described by the consequence, with the focus on Cancel', () => {
    setup()
    const dialog = screen.getByRole('alertdialog', { name: 'Remove bob?', description: 'bob loses access at once.' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('is a plain dialog, still described, and puts no focus on Cancel when not destructive', () => {
    setup({ destructive: false, title: 'Change the role', description: 'Applies with their next request.' })
    const dialog = screen.getByRole('dialog', { name: 'Change the role', description: 'Applies with their next request.' })
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).not.toHaveFocus()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('confirms, and closes on Cancel, Escape and the backdrop while idle', async () => {
    const { onClose, onConfirm, user } = setup()
    const dialog = screen.getByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }))
    expect(onConfirm).toHaveBeenCalledOnce()
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await user.keyboard('{Escape}')
    await user.click(backdropOf(dialog))
    expect(onClose).toHaveBeenCalledTimes(3)
  })

  describe('while pending', () => {
    it('ignores Escape, the backdrop and Cancel, and does not confirm again', async () => {
      const { onClose, onConfirm, user } = setup({ pending: true })
      const dialog = screen.getByRole('alertdialog')
      await user.keyboard('{Escape}')
      await user.click(backdropOf(dialog))
      await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
      await user.click(within(dialog).getByRole('button', { name: 'Remove' }))
      expect(onClose).not.toHaveBeenCalled()
      expect(onConfirm).not.toHaveBeenCalled()
      expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    })

    // disabled would move the focus to the body: the keyboard user loses their place.
    it('keeps both buttons focusable: aria-disabled, never disabled, and confirm is busy', () => {
      setup({ pending: true })
      const cancel = screen.getByRole('button', { name: 'Cancel' })
      const remove = screen.getByRole('button', { name: 'Remove' })
      for (const button of [cancel, remove]) {
        expect(button).toHaveAttribute('aria-disabled', 'true')
        expect(button).not.toBeDisabled()
      }
      expect(remove).toHaveAttribute('aria-busy', 'true')
      expect(cancel).not.toHaveAttribute('aria-busy', 'true')
    })

    it('keeps the focus on the button that had it when the action starts', async () => {
      const { rerender, user } = setup()
      const remove = screen.getByRole('button', { name: 'Remove' })
      await user.click(remove)
      expect(remove).toHaveFocus()
      rerender({ pending: true })
      expect(remove).toHaveFocus()
    })
  })

  it('shows the error inside the dialog, as part of its description, and stays open', () => {
    setup({ error: 'A lab needs at least one active manager.' })
    const dialog = screen.getByRole('alertdialog', {
      name: 'Remove bob?',
      description: 'bob loses access at once. A lab needs at least one active manager.',
    })
    expect(within(dialog).getByRole('alert')).toHaveTextContent('A lab needs at least one active manager.')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })

  it('has no busy state and no error by default', () => {
    setup()
    expect(screen.getByRole('button', { name: 'Remove' })).toHaveAttribute('aria-busy', 'false')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  describe('with a form', () => {
    it('submits the form from the confirm button, but not while pending', async () => {
      const onSubmit = vi.fn<() => void>()
      const user = userEvent.setup()
      const { rerender } = render(<FormDialog pending={false} onSubmit={onSubmit} />)
      await user.click(screen.getByRole('button', { name: 'Save' }))
      expect(onSubmit).toHaveBeenCalledOnce()
      rerender(<FormDialog pending onSubmit={onSubmit} />)
      await user.click(screen.getByRole('button', { name: 'Save' }))
      expect(onSubmit).toHaveBeenCalledOnce()
    })
  })
})
