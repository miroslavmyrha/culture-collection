import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { makeBatch, makeHistoryLine, makeLab, makeMe, makePassage, makeStrain, makeTaxon, makeTerms, makeUnitRow, makeVial, page } from '@/test/factories'
import { mockApi } from '@/test/mockApi'
import { renderApp } from '@/test/render'

// The strain page by task (#19): each tab is its own URL and asks only for its own data, the
// tabs are links switched by keyboard, and a regulated strain's places stay masked on every tab.

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const STRAIN = '/api/v1/labs/{lab_public_id}/strains/{public_id}/'
const TERMS = '/api/v1/labs/{lab_public_id}/strains/{public_id}/terms/'
const HISTORY = '/api/v1/labs/{lab_public_id}/strains/{public_id}/history/'
const PASSAGES = '/api/v1/labs/{lab_public_id}/passages/'
const BATCHES = '/api/v1/labs/{lab_public_id}/batches/'
const VIALS = '/api/v1/labs/{lab_public_id}/vials/'
const UNITS = '/api/v1/labs/{lab_public_id}/storage-units/'
const BASE = `/labs/${LAB_ID}/strains/${STRAIN_ID}`

// Invented taxa: the tests pair them with restrictions.
const GMO = {
  public_id: '00000000-0000-4000-8000-0000000000e1',
  kind: 'gmo' as const,
  reference: 'MŽP 2026/12',
  act: '',
  gmo_category: 2,
  created_at: '2026-02-01T10:00:00Z',
  ended_at: null,
  end_reason: '',
}
const regulated = makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42', taxon: makeTaxon({ name: 'Testella exempli' }), restriction_history: [GMO] })
const freezer = makeUnitRow({ name: 'Freezer Secret' })
const box = makeUnitRow({ kind: 'box', name: 'Box Secret', parent: freezer.public_id, rows: 9, cols: 9, max_risk_group: null })

type Role = 'viewer' | 'technician' | 'manager'

/** Every tab's data, each read counted. The masked vial is as the API sends it: no place. */
function strainPage(role: Role, canReveal = false) {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
  mockApi('get', UNITS, [freezer, box])
  return {
    strain: mockApi('get', STRAIN, regulated),
    terms: mockApi('get', TERMS, { deposit: null, versions: [makeTerms()] }),
    history: mockApi('get', HISTORY, page([makeHistoryLine({ summary: 'placed vial MYC 42 / 1 / 1' })])),
    passages: mockApi('get', PASSAGES, page([makePassage({ number: 0 })])),
    batches: mockApi('get', BATCHES, page([makeBatch()])),
    vials: mockApi('get', VIALS, page([makeVial({ label: 'MYC 42 / 1 / 1', placed: true, location_masked: true, can_reveal: canReveal })])),
  }
}

const TABS = [
  ['Overview', '', () => screen.findByRole('heading', { level: 2, name: 'Terms of use' }, { timeout: 5000 }), ['strain', 'terms']],
  ['Material', '/material', () => screen.findByRole('table', { name: 'Vials' }, { timeout: 5000 }), ['strain', 'passages', 'batches', 'vials']],
  ['Terms', '/terms', () => screen.findByRole('article', { name: 'Version 1' }, { timeout: 5000 }), ['strain', 'terms']],
  ['History', '/history', () => screen.findByRole('list', { name: 'History, newest first' }, { timeout: 5000 }), ['strain', 'history']],
] as const

describe('the strain page in tabs (#19)', { timeout: 30_000 }, () => {
  it.each(TABS)('%s asks only for its own data', async (_, tail, shown, reads) => {
    const calls = strainPage('viewer')
    renderApp({ path: BASE + tail })
    await shown()
    // Settled: nothing else arrives later.
    await new Promise((resolve) => setTimeout(resolve, 50))
    const counts = Object.fromEntries(Object.entries(calls).map(([name, list]) => [name, list.length]))
    expect(counts).toEqual(Object.fromEntries(Object.keys(calls).map((name) => [name, (reads as readonly string[]).includes(name) ? 1 : 0])))
  })

  it('marks the open tab, and switches tabs by keyboard with the focus on the strain', async () => {
    strainPage('viewer')
    const { router } = renderApp({ path: BASE })
    await TABS[0][2]()
    const nav = screen.getByRole('navigation', { name: 'Strain sections' })
    const current = () => within(nav).getAllByRole('link').filter((link) => link.getAttribute('aria-current') === 'page').map((link) => link.textContent)
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Overview', 'Material', 'Terms', 'History'])
    expect(current()).toEqual(['Overview'])
    const user = userEvent.setup()
    // Tab reaches the tab links in order; Enter opens one.
    within(nav).getByRole('link', { name: 'Overview' }).focus()
    await user.tab()
    expect(within(nav).getByRole('link', { name: 'Material' })).toHaveFocus()
    await user.keyboard('{Enter}')
    await screen.findByRole('table', { name: 'Vials' }, { timeout: 5000 })
    expect(router.state.location.pathname).toBe(`${BASE}/material`)
    expect(current()).toEqual(['Material'])
    // The layout puts the focus on the page's h1, the strain, as after every navigation.
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'MYC 42' })).toHaveFocus())
    await user.click(within(nav).getByRole('link', { name: 'History' }))
    await screen.findByRole('list', { name: 'History, newest first' }, { timeout: 5000 })
    expect(current()).toEqual(['History'])
    expect(document.title).toBe('MYC 42, history | Culture collection')
  })

  const EVERY_TAB = TABS.flatMap(([name, tail, shown]) => (['viewer', 'manager'] as const).map((role) => [name, role, tail, shown] as const))

  it.each(EVERY_TAB)("%s keeps a regulated strain's places masked for a %s", async (name, role, tail, shown) => {
    const calls = strainPage(role)
    renderApp({ path: BASE + tail })
    await shown()
    const text = document.body.textContent ?? ''
    expect(text).not.toContain('Freezer Secret')
    expect(text).not.toContain('Box Secret')
    // Material shows the vial as hidden; the other tabs never ask for the vials, so no place can reach them.
    const material = name === 'Material'
    expect(screen.queryAllByText('Hidden: regulated strain')).toHaveLength(material ? 1 : 0)
    expect(calls.vials).toHaveLength(material ? 1 : 0)
    expect(screen.queryByRole('button', { name: /Reveal the location/ })).not.toBeInTheDocument()
  })

  it.each(TABS)('%s offers the reveal of a masked place only on Material, to a holder of the grant', async (name, tail, shown) => {
    strainPage('manager', true)
    renderApp({ path: BASE + tail })
    await shown()
    expect(screen.queryAllByRole('button', { name: /Reveal the location/ })).toHaveLength(name === 'Material' ? 1 : 0)
  })
})
