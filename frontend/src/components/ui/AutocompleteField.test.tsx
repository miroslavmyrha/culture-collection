import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createRef } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { AutocompleteField } from './AutocompleteField'

type Item = { id: string; name: string }
const ITEMS: Item[] = [
  { id: '1', name: 'Bacillus' },
  { id: '2', name: 'Escherichia' },
]

function setup(props: Partial<Parameters<typeof AutocompleteField<Item>>[0]> = {}) {
  const onChange = vi.fn<(value: Item | null) => void>()
  const onInputChange = vi.fn<(text: string) => void>()
  const ref = createRef<HTMLInputElement>()
  render(
    <AutocompleteField<Item>
      label="Taxon"
      hint="Type part of the name"
      options={ITEMS}
      value={null}
      onChange={onChange}
      inputValue=""
      onInputChange={onInputChange}
      getOptionLabel={(item) => item.name}
      getOptionKey={(item) => item.id}
      isOptionEqualToValue={(a, b) => a.id === b.id}
      ref={ref}
      {...props}
    />,
  )
  return { onChange, onInputChange, ref }
}

describe('AutocompleteField', () => {
  it('is a combobox named by its label and described by hint and error', () => {
    setup({ error: 'Choose a taxon' })
    const input = screen.getByRole('combobox', { name: 'Taxon' })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Type part of the name Choose a taxon')
  })

  // A Controller focuses the field through this ref: on MUI's wrapper it would focus nothing.
  it('passes the ref to the input element', () => {
    const { ref } = setup()
    expect(ref.current).toBe(screen.getByRole('combobox', { name: 'Taxon' }))
  })

  it('opens the list with ArrowDown and picks with Enter', async () => {
    const { onChange } = setup()
    const user = userEvent.setup()
    screen.getByRole('combobox', { name: 'Taxon' }).focus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Bacillus', 'Escherichia'])
    // The first ArrowDown only opened the list: two more reach the second option.
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(onChange).toHaveBeenLastCalledWith(ITEMS[1])
  })

  it('shows the options it is given, unfiltered: the caller searched already', async () => {
    setup({ inputValue: 'zzz' })
    const user = userEvent.setup()
    await user.click(screen.getByRole('combobox', { name: 'Taxon' }))
    expect(screen.getAllByRole('option')).toHaveLength(2)
  })
})
