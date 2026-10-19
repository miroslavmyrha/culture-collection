import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createRef } from 'react'
import { describe, expect, it } from 'vitest'
import { SelectField } from './SelectField'

const OPTIONS = [
  { value: 'viewer', label: 'Viewer' },
  { value: 'manager', label: 'Manager' },
]

describe('SelectField', () => {
  // A native select always shows an option, also for '' ("All"): MUI must not draw the label on it.
  it('keeps its label above the box also when the value is empty', () => {
    render(<SelectField label="Risk group" options={[{ value: '', label: 'All' }, ...OPTIONS]} />)
    expect(screen.getByText('Risk group', { selector: 'label' })).toHaveAttribute('data-shrink', 'true')
  })

  it('is a native select named by its label, with every option', () => {
    render(<SelectField label="Role" options={OPTIONS} />)
    const select = screen.getByRole('combobox', { name: 'Role' })
    expect(select.tagName).toBe('SELECT')
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Viewer', 'Manager'])
  })

  it('describes the select by hint and error and marks it invalid', () => {
    render(<SelectField label="Role" options={OPTIONS} hint="Up to your own role" error="Pick a role" />)
    const select = screen.getByRole('combobox', { name: 'Role' })
    expect(select).toHaveAttribute('aria-invalid', 'true')
    expect(select).toHaveAccessibleDescription('Up to your own role Pick a role')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('changes its value with the keyboard like any select', async () => {
    render(<SelectField label="Role" options={OPTIONS} />)
    await userEvent.setup().selectOptions(screen.getByRole('combobox', { name: 'Role' }), 'manager')
    expect(screen.getByRole('combobox', { name: 'Role' })).toHaveValue('manager')
  })

  // react-hook-form focuses the first invalid field through this ref.
  it('passes the ref to the select element', () => {
    const ref = createRef<HTMLSelectElement>()
    render(<SelectField label="Role" options={OPTIONS} ref={ref} />)
    expect(ref.current).toBe(screen.getByRole('combobox', { name: 'Role' }))
  })
})
