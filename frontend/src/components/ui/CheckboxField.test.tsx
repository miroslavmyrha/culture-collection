import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createRef } from 'react'
import { useForm } from 'react-hook-form'
import { describe, expect, it } from 'vitest'
import { CheckboxField } from './CheckboxField'

function Group({ onValues }: { onValues: (values: string[]) => void }) {
  const { register, handleSubmit } = useForm<{ picked: string[] }>({ defaultValues: { picked: [] } })
  return (
    <form onSubmit={handleSubmit((values) => onValues(values.picked))}>
      <CheckboxField label="Teaching" value="teaching" {...register('picked')} />
      <CheckboxField label="Diagnostics" value="diagnostics" {...register('picked')} />
      <button type="submit">Save</button>
    </form>
  )
}

describe('CheckboxField', () => {
  it('labels the box and passes the ref to the input', () => {
    const ref = createRef<HTMLInputElement>()
    render(<CheckboxField label="Teaching" ref={ref} />)
    expect(ref.current).toBe(screen.getByRole('checkbox', { name: 'Teaching' }))
  })

  it('gives react-hook-form the checked values of one name as a list', async () => {
    const user = userEvent.setup()
    let picked: string[] | undefined
    render(<Group onValues={(values) => (picked = values)} />)
    await user.click(screen.getByRole('checkbox', { name: 'Diagnostics' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByRole('checkbox', { name: 'Diagnostics', checked: true })
    expect(picked).toEqual(['diagnostics'])
  })
})
