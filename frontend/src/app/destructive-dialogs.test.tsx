import { screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import { RejectDialog } from '@/features/deposits/components/DepositDialogs'
import { RemoveMemberDialog } from '@/features/labs/components/RemoveMemberDialog'
import { makeDeposit, makeMember } from '@/test/factories'
import { renderWithProviders } from '@/test/render'

/**
 * Invariant: every destructive confirmation says what it will cost, as the accessible
 * description of its alertdialog (WAI-ARIA alertdialog, WCAG 1.3.1), so a screen reader reads
 * the consequence with the question. A new `destructive` ConfirmDialog fails here until it is
 * listed with the consequence its description must carry.
 */
const DESTRUCTIVE: Record<string, { render: () => ReactElement; name: string; consequence: string }> = {
  '/src/features/labs/components/RemoveMemberDialog.tsx': {
    render: () => (
      <RemoveMemberDialog
        labId="00000000-0000-4000-8000-00000000000a"
        labName="Mycology"
        member={makeMember({ username: 'bob' })}
        open
        onClose={() => {}}
        onExited={() => {}}
      />
    ),
    name: 'Remove bob?',
    consequence: 'bob leaves Mycology and loses access to it at once.',
  },
  '/src/features/deposits/components/DepositDialogs.tsx': {
    render: () => (
      <RejectDialog
        labId="00000000-0000-4000-8000-00000000000a"
        deposit={makeDeposit({ name_as_received: 'Testella exempli K3', status: 'checking' })}
        open
        onClose={() => {}}
        onExited={() => {}}
      />
    ),
    name: 'Reject Testella exempli K3?',
    consequence: 'The deposit ends here and becomes no strain. The decision cannot be undone',
  },
}

const sources = import.meta.glob<string>('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true })

describe('destructive confirmations (invariant)', () => {
  it('has the source files to check', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(10)
  })

  it('lists every file that opens a destructive ConfirmDialog', () => {
    const found = Object.entries(sources)
      .filter(([path, text]) => !path.endsWith('.test.tsx') && !path.startsWith('/src/components/ui/') && /<ConfirmDialog\b[^>]*\bdestructive\b/s.test(text))
      .map(([path]) => path)
      .toSorted()
    expect(found).toEqual(Object.keys(DESTRUCTIVE).toSorted())
  })

  it.each(Object.entries(DESTRUCTIVE))('%s describes its alertdialog by the consequence', async (_, { render, name, consequence }) => {
    await renderWithProviders(render())
    const dialog = await screen.findByRole('alertdialog', { name })
    expect(dialog).toHaveAccessibleDescription(expect.stringContaining(consequence))
  })
})
