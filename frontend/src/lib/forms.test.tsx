import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useForm } from 'react-hook-form'
import { describe, expect, it } from 'vitest'
import { TextField } from '@/components/ui'
import { renderWithProviders } from '@/test/render'
import { problem, validationProblem } from '@/test/factories'
import { ApiError } from './api'
import { applyServerErrors } from './forms'

type Values = { name: string; code: string }

/** A minimal form wired the way feature forms are: TextField, applyServerErrors, one root alert. */
function Form({ error }: { error: unknown }) {
  const { register, handleSubmit, setError, formState } = useForm<Values>({ defaultValues: { name: '', code: '' } })
  const onSubmit = handleSubmit(() => {
    applyServerErrors(error, ['name', 'code'], setError)
  })
  return (
    <form onSubmit={onSubmit} aria-label="Edit">
      <TextField label="Name" hint="Shown on labels" error={formState.errors.name?.message} {...register('name')} />
      <TextField label="Code" error={formState.errors.code?.message} {...register('code')} />
      {formState.errors.root?.server && <p role="alert">{formState.errors.root.server.message}</p>}
      <button type="submit">Save</button>
    </form>
  )
}

async function submitWith(error: unknown) {
  const user = userEvent.setup()
  await renderWithProviders(<Form error={error} />)
  await user.click(screen.getByRole('button', { name: 'Save' }))
  return user
}

describe('applyServerErrors', () => {
  it('maps a DRF field dict onto the fields, focuses the first, links the message', async () => {
    const user = await submitWith(new ApiError(400, { code: ['Already exists.'], name: ['Too long.'] }))
    const name = screen.getByRole('textbox', { name: 'Name' })
    const code = screen.getByRole('textbox', { name: 'Code' })
    expect(code).toHaveAttribute('aria-invalid', 'true')
    expect(code).toHaveAccessibleDescription('Already exists.')
    expect(name).toHaveAccessibleDescription('Shown on labels Too long.')
    expect(code).toHaveFocus() // first error in the body order
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    // Typing clears the server error: the field re-validates on change after a submit.
    await user.type(code, 'x')
    expect(code).toHaveAttribute('aria-invalid', 'false')
    expect(code).not.toHaveAttribute('aria-describedby')
  })

  it('maps problem details: attr to fields, the rest into one form message', async () => {
    await submitWith(
      new ApiError(
        400,
        validationProblem([
          { attr: 'name', code: 'unique', detail: 'Name taken.' },
          { attr: 'name', code: 'other', detail: 'Second message is dropped.' },
          { attr: 'non_field_errors', code: 'invalid', detail: 'Pick another slot.' },
          { attr: null, code: 'invalid', detail: 'Try later.' },
        ]),
      ),
    )
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveAccessibleDescription('Shown on labels Name taken.')
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveFocus()
    expect(screen.getByRole('alert')).toHaveTextContent('Pick another slot. Try later.')
  })

  it('puts non_field_errors, detail and unknown keys into one message', async () => {
    await submitWith(new ApiError(400, { non_field_errors: ['Overlaps.'], unknown: ['Ignored field.'], detail: 'Bad.' }))
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByRole('alert')).toHaveTextContent('Overlaps. Ignored field. Bad.')
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveAttribute('aria-invalid', 'false')
  })

  it('uses the problem detail when there is no errors list', async () => {
    await submitWith(new ApiError(400, problem(400, { detail: 'Box is full.' })))
    expect(screen.getByRole('alert')).toHaveTextContent('Box is full.')
  })

  it.each([
    ['a 500', new ApiError(500, { name: ['x'] })],
    ['a 403', new ApiError(403, problem(403))],
    ['a plain error', new Error('x')],
    ['an empty body', new ApiError(400, undefined)],
    ['nested field array errors', new ApiError(400, { items: [{}, { qty: ['Too many.'] }] })],
  ])('maps nothing for %s and returns false', (_name, error) => {
    const calls: unknown[] = []
    expect(applyServerErrors<Values>(error, ['name'], (...args) => calls.push(args))).toBe(false)
    expect(calls).toEqual([])
  })
})
