import { render, screen } from '@testing-library/react'
import { createRef } from 'react'
import { describe, expect, it } from 'vitest'
import { TextField } from './TextField'

describe('TextField', () => {
  it('labels the input and describes it by hint and error', () => {
    render(<TextField label="Name" hint="Max 100 characters" error="Enter a name" />)
    const input = screen.getByRole('textbox', { name: 'Name' })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Max 100 characters Enter a name')
    // Described, not announced: no alert per field.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('has no description and is valid without hint and error', () => {
    render(<TextField label="Name" />)
    const input = screen.getByRole('textbox', { name: 'Name' })
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(input).not.toHaveAttribute('aria-describedby')
  })

  it('keeps the hint as the description while there is no error', () => {
    render(<TextField label="Name" hint="Max 100 characters" />)
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveAccessibleDescription('Max 100 characters')
  })

  it('gives two fields different ids', () => {
    render(
      <>
        <TextField label="A" />
        <TextField label="B" />
      </>,
    )
    expect(screen.getByRole('textbox', { name: 'A' }).id).not.toBe(screen.getByRole('textbox', { name: 'B' }).id)
  })

  // react-hook-form focuses the first invalid field through this ref: on MUI's wrapper div it
  // would focus nothing.
  it('passes the ref to the input element', () => {
    const ref = createRef<HTMLInputElement>()
    render(<TextField label="Name" ref={ref} />)
    expect(ref.current).toBe(screen.getByRole('textbox', { name: 'Name' }))
  })
})
