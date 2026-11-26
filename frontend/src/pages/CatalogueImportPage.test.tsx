import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { makeLab, makeMe } from '@/test/factories'
import { mockApi } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LAB = '/api/v1/labs/{public_id}/'
const CHECK = '/api/v1/labs/{lab_public_id}/deposits/catalogue-check/'
const IMPORT = '/api/v1/labs/{lab_public_id}/deposits/catalogue-import/'
const SHA = 'a'.repeat(64)
const path = `/labs/${LAB_ID}/catalogue-import`
const file = () => new File(['accession_number,name_as_received\n'], 'catalogue.csv', { type: 'text/csv' })

function signedIn(role: 'manager' | 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', LAB, makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

// A multipart body does not pass MSW under jsdom: the POSTs are answered at the client, as in
// the permit tests, and the form data is read from the serializer the call carries.
const json = (status: number) => new Response('{}', { status, headers: { 'Content-Type': 'application/json' } })
const spyPost = () => vi.spyOn(api, 'POST')

function sentForm(post: ReturnType<typeof spyPost>, index: number): FormData {
  const [, init]: unknown[] = post.mock.calls[index] ?? []
  const serializer: unknown = typeof init === 'object' && init !== null ? Reflect.get(init, 'bodySerializer') : undefined
  if (typeof serializer !== 'function') throw new Error('sent without its form data')
  const sent: unknown = Reflect.apply(serializer, undefined, [])
  if (!(sent instanceof FormData)) throw new Error('not form data')
  return sent
}

afterEach(() => vi.restoreAllMocks())

async function pickAndCheck() {
  const user = userEvent.setup()
  await user.upload(await screen.findByLabelText('Catalogue file', {}, { timeout: 5000 }), file())
  await user.click(screen.getByRole('button', { name: 'Check the file' }))
  return user
}

describe('CatalogueImportPage', () => {
  it('tells a member who is no manager that only managers import', async () => {
    signedIn('curator')
    renderApp({ path })
    expect(await screen.findByText('Only managers import a catalogue.', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByLabelText('Catalogue file')).not.toBeInTheDocument()
  })

  it('offers the template to download', async () => {
    signedIn('manager')
    renderApp({ path })
    const link = await screen.findByRole('link', { name: 'Download the template' }, { timeout: 5000 })
    expect(new URL(link.getAttribute('href') ?? '').pathname).toBe(`/api/v1/labs/${LAB_ID}/deposits/catalogue-template/`)
  })

  it('lists every row error and offers no import while a row fails', async () => {
    signedIn('manager')
    spyPost().mockResolvedValueOnce({
      data: {
        sha256: SHA,
        rows: 3,
        row_errors: [
          { row: 3, column: 'taxon', message: 'No taxon has this name here.' },
          { row: 4, column: '', message: 'The row is refused.' },
        ],
      },
      response: json(200),
    })
    renderApp({ path })
    await pickAndCheck()
    expect(await screen.findByText(/2 errors in 3 rows/)).toBeInTheDocument()
    const rows = within(screen.getByRole('table')).getAllByRole('row')
    expect(rows.slice(1).map((r) => r.textContent)).toEqual(['3taxonNo taxon has this name here.', '4The rowThe row is refused.'])
    expect(screen.getByRole('region', { name: 'Row errors table' })).toHaveAttribute('tabindex', '0')
    expect(screen.queryByRole('button', { name: /^Import/ })).not.toBeInTheDocument()
  })

  it('imports the checked file with its hash and a reason, and links the new strains', async () => {
    signedIn('manager')
    const post = spyPost()
      .mockResolvedValueOnce({ data: { sha256: SHA, rows: 2, row_errors: [] }, response: json(200) })
      .mockResolvedValueOnce({
        data: {
          strains: [
            { public_id: '00000000-0000-4000-8000-000000000001', accession_number: 'MYC 40', former_number: '' },
            { public_id: '00000000-0000-4000-8000-000000000002', accession_number: 'MYC 41', former_number: 'CCM 4517' },
          ],
        },
        response: json(201),
      })
    renderApp({ path })
    const user = await pickAndCheck()
    expect(await screen.findByText('All 2 rows can be imported.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Import 2 strains' }))
    expect(screen.getByRole('textbox', { name: /Reason/ })).toHaveAccessibleDescription(/Give the reason for the import\./)
    expect(post).toHaveBeenCalledTimes(1)
    await user.type(screen.getByRole('textbox', { name: /Reason/ }), 'The former paper catalogue.')
    await user.click(screen.getByRole('button', { name: 'Import 2 strains' }))
    expect(await screen.findByText('Imported 2 strains.')).toBeInTheDocument()
    expect(post).toHaveBeenCalledTimes(2)
    expect(post.mock.calls.map((call: unknown[]) => call[0])).toEqual([CHECK, IMPORT])
    const sent = sentForm(post, 1)
    const sentFile = sent.get('file')
    expect([sent.get('sha256'), sent.get('reason'), sentFile instanceof File ? sentFile.name : sentFile]).toEqual([
      SHA,
      'The former paper catalogue.',
      'catalogue.csv',
    ])
    const list = screen.getByRole('list', { name: 'Imported strains' })
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((i) => i.textContent),
    ).toEqual(['MYC 40', 'MYC 41 (formerly CCM 4517)'])
  })

  it('shows the import’s own refusal in its words', async () => {
    signedIn('manager')
    spyPost().mockResolvedValueOnce({
      error: {
        type: 'about:blank',
        title: 'Unprocessable Entity',
        status: 422,
        detail: 'Use the columns of the template, each once.',
        code: 'catalogue_refused',
        errors: [],
      },
      response: json(422),
    })
    renderApp({ path })
    await pickAndCheck()
    expect(await screen.findByText('Use the columns of the template, each once.')).toBeInTheDocument()
  })
})
