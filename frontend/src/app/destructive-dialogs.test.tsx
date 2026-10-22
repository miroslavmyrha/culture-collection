import { screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import { RejectDialog } from '@/features/deposits/components/DepositDialogs'
import { CancelDialog, ConfirmShipmentDialog, WithdrawShipmentDialog } from '@/features/distribution/components/RequestDialogs'
import { EndPermitDialog } from '@/features/distribution/components/RequesterDialogs'
import { RemoveMemberDialog } from '@/features/labs/components/RemoveMemberDialog'
import { UnitStatusDialog } from '@/features/storage/components/UnitDialogs'
import { CheckErrorDialog } from '@/features/vials/components/CheckDialogs'
import { ReviveDialog } from '@/features/vials/components/VialDialogs'
import { makeCheck, makeDeposit, makeMember, makePermit, makePreparation, makeRequest, makeRequestLine, makeUnit, makeVial } from '@/test/factories'
import { renderWithProviders } from '@/test/render'

/**
 * Invariant: every destructive confirmation says what it will cost, as the accessible
 * description of its alertdialog (WAI-ARIA alertdialog, WCAG 1.3.1), so a screen reader reads
 * the consequence with the question. A new `destructive` ConfirmDialog fails here until it is
 * listed with the consequence its description must carry. A file with several lists each.
 */
type Entry = { render: () => ReactElement; name: string; consequence: string }
const DESTRUCTIVE: Record<string, Entry | Entry[]> = {
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
  '/src/features/storage/components/UnitDialogs.tsx': {
    render: () => (
      <UnitStatusDialog
        labId="00000000-0000-4000-8000-00000000000a"
        unit={makeUnit({ name: 'Rack 1', kind: 'rack' })}
        to="retired"
        open
        onClose={() => {}}
        onExited={() => {}}
      />
    ),
    name: 'Retire Rack 1?',
    consequence: 'A retired unit stays in the history but changes no more and takes nothing. This cannot be undone.',
  },
  '/src/features/vials/components/VialDialogs.tsx': {
    render: () => (
      <ReviveDialog
        labId="00000000-0000-4000-8000-00000000000a"
        strainId="00000000-0000-4000-8000-0000000000d1"
        vial={makeVial({ label: 'MYC 42 / 1 / 3' })}
        open
        onClose={() => {}}
        onExited={() => {}}
      />
    ),
    name: 'Revive vial MYC 42 / 1 / 3?',
    consequence: 'The vial is used up and leaves its position, and a new passage starts from it. This cannot be undone.',
  },
  '/src/features/vials/components/CheckDialogs.tsx': {
    render: () => (
      <CheckErrorDialog
        labId="00000000-0000-4000-8000-00000000000a"
        strainId="00000000-0000-4000-8000-0000000000d1"
        check={makeCheck({ kind: 'purity', checked_on: '2026-10-02' })}
        open
        onClose={() => {}}
        onExited={() => {}}
      />
    ),
    name: 'Enter the purity check of 2026-10-02 in error?',
    consequence: 'no longer counts for a release. A released batch that loses a passed check waits for its checks again. This cannot be undone.',
  },
  '/src/features/distribution/components/RequestDialogs.tsx': [
    {
      render: () => (
        <CancelDialog
          labId="00000000-0000-4000-8000-00000000000a"
          request={makeRequest({ number: '2026/7', status: 'approved', lines: [makeRequestLine({ reserved: [{ public_id: '00000000-0000-4000-8000-0000000000e1', label: 'MYC 1 / 1 / 1' }, { public_id: '00000000-0000-4000-8000-0000000000e2', label: 'MYC 1 / 1 / 2' }] })] })}
          open
          onClose={() => {}}
          onExited={() => {}}
        />
      ),
      name: 'Cancel request 2026/7?',
      consequence: 'The request is withdrawn and its 2 reserved vials are available again. It cannot be undone.',
    },
    {
      render: () => (
        <ConfirmShipmentDialog
          labId="00000000-0000-4000-8000-00000000000a"
          request={makeRequest({ number: '2026/7', status: 'awaiting_confirmation', lines: [makeRequestLine({ reserved: [{ public_id: '00000000-0000-4000-8000-0000000000e1', label: 'MYC 1 / 1 / 1' }] })] })}
          preparation={makePreparation({ prepared_by: 'curator' })}
          open
          onClose={() => {}}
          onExited={() => {}}
        >
          {null}
        </ConfirmShipmentDialog>
      ),
      name: 'Confirm the shipment of request 2026/7?',
      consequence: 'Its reserved vial leaves the collection today, as prepared by curator: recorded as distributed and out of their boxes. A shipment cannot be undone.',
    },
    {
      render: () => (
        <WithdrawShipmentDialog
          labId="00000000-0000-4000-8000-00000000000a"
          request={makeRequest({ number: '2026/7', status: 'awaiting_confirmation' })}
          open
          onClose={() => {}}
          onExited={() => {}}
        />
      ),
      name: 'Withdraw the prepared shipment of request 2026/7?',
      consequence: 'The request is approved again and its vials stay reserved. The prepared shipment is kept with the reason',
    },
  ],
  '/src/features/distribution/components/RequesterDialogs.tsx': {
    render: () => (
      <EndPermitDialog labId="00000000-0000-4000-8000-00000000000a" permit={makePermit({ reference: 'DEV/9' })} open onClose={() => {}} onExited={() => {}} />
    ),
    name: 'End DEV/9?',
    consequence: 'From that day the permit no longer counts for a request. It cannot be undone',
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

  const entries = Object.entries(DESTRUCTIVE).flatMap(([file, entry]) => (Array.isArray(entry) ? entry : [entry]).map((e) => [`${file}: ${e.name}`, e] as const))
  it.each(entries)('%s describes its alertdialog by the consequence', async (_, { render, name, consequence }) => {
    await renderWithProviders(render())
    const dialog = await screen.findByRole('alertdialog', { name })
    expect(dialog).toHaveAccessibleDescription(expect.stringContaining(consequence))
  })
})
