import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Field } from './Field'

describe('Field', () => {
  it('labels the control and describes it by hint and error', () => {
    render(
      <Field label="Name" hint="Max 100 characters" error="Enter a name">
        {(control) => <input {...control} />}
      </Field>,
    )
    const input = screen.getByRole('textbox', { name: 'Name' })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Max 100 characters Enter a name')
    // Described, not announced: no alert per field.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('has no description and is valid without hint and error', () => {
    render(<Field label="Name">{(control) => <input {...control} />}</Field>)
    const input = screen.getByRole('textbox', { name: 'Name' })
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(input).not.toHaveAttribute('aria-describedby')
  })

  it('gives two fields different ids', () => {
    render(
      <>
        <Field label="A">{(control) => <input {...control} />}</Field>
        <Field label="B">{(control) => <input {...control} />}</Field>
      </>,
    )
    expect(screen.getByRole('textbox', { name: 'A' }).id).not.toBe(screen.getByRole('textbox', { name: 'B' }).id)
  })
})
