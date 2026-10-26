import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, watchCsp } from './support.js'

// Each test walks several pages and scans them with axe: real work, 5 to 25 s on a quiet machine and over
// the 30 s default on a busy one (#60).
test.describe.configure({ timeout: 120_000 })

// Home (#69) against the real API (seed_e2e: e2e-curator and e2e-viewer in "E2E lab", the
// depositor "E2E Depositor"). The curator's test receives a deposit through the API with a name
// unique to the run, follows it from Home, and rejects it at the end, so nothing it made keeps
// waiting for the next run. The viewer's test changes nothing.

const RUN = Date.now().toString(36)

async function as(browser: Browser, username: string, options: { width?: number; colorScheme?: 'light' | 'dark' } = {}) {
  const width = options.width ?? 1280
  const context = await browser.newContext({ storageState: signedInAs(username), viewport: { width, height: width === 320 ? 640 : 900 }, colorScheme: options.colorScheme ?? 'light' })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

type Row = Record<string, unknown>

/** A request with the page's session and CSRF token; answers the JSON body. */
async function call(page: Page, path: string, body?: Row): Promise<Row> {
  const answer = await page.evaluate(
    async ([url, payload]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
      const init: RequestInit = payload === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) }, body: JSON.stringify(payload) }
      const response = await fetch(url, init)
      return { status: response.status, text: await response.text() }
    },
    [path, body] as const,
  )
  expect(answer.status, `${path}: ${answer.text}`).toBeLessThan(300)
  const json: unknown = JSON.parse(answer.text)
  return isRow(json) ? json : {}
}

const isRow = (value: unknown): value is Row => typeof value === 'object' && value !== null && !Array.isArray(value)
const results = (json: Row): Row[] => {
  const list: unknown = json.results
  return Array.isArray(list) ? list.filter(isRow) : []
}
const USES = ['research_noncommercial', 'research_commercial', 'teaching', 'diagnostics', 'production', 'reference_qc', 'patent_deposit_related', 'redistribution']

/** A deposit received today in the seeded lab, as the page's user: its lab and id. */
async function receive(page: Page, name: string) {
  const lab = String(results(await call(page, '/api/v1/labs/?limit=200')).find((row) => row.name === 'E2E lab')?.public_id)
  const depositor = results(await call(page, `/api/v1/labs/${lab}/depositors/?search=E2E`))[0]
  const terms = { mta: null, abs_scope: 'not_in_scope', country_of_origin: 'CZ', uses: USES.map((use) => ({ use, decision: 'permit' })) }
  const body = { depositor: depositor?.public_id, received_on: new Date().toLocaleDateString('sv'), condition: 'intact', name_as_received: name, terms }
  const deposit = await call(page, `/api/v1/labs/${lab}/deposits/`, body)
  return { lab, id: String(deposit.public_id) }
}

test('a curator finds a waiting deposit on Home and follows it to the deposit, by keyboard; Home passes axe in both schemes and fits 320 px', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator')
  const violations = await watchCsp(page)
  await page.goto('/')
  const name = `Bacillus subtilis H-${RUN}`
  const deposit = await receive(page, name)
  await page.reload()
  const waiting = page.getByRole('region', { name: /^Waiting for you/ })
  const group = waiting.getByRole('region', { name: /^Deposits received/ })
  const link = group.getByRole('link', { name })
  await expect(link).toBeVisible()
  await expect(group.getByRole('listitem').filter({ has: page.getByRole('link', { name }) })).toContainText('Received, not checked yet')
  await expect(page.getByRole('region', { name: 'Quick actions' }).getByRole('link', { name: 'Receive a deposit' })).toBeVisible()
  expect(await axe(page, 'main')).toEqual([])

  await link.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(`/labs/${deposit.lab}/deposits/${deposit.id}`)
  await expect(page.getByRole('heading', { level: 1, name: `Deposit ${name}` })).toBeFocused()
  // The lab tabs count it among the deposits to check.
  await expect(page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: /^Deposits, \d+ to check$/ })).toBeVisible()

  for (const [width, colorScheme] of [[1280, 'dark'], [320, 'light']] as const) {
    const other = await as(browser, 'e2e-curator', { width, colorScheme })
    await other.page.goto('/')
    await expect(other.page.getByRole('region', { name: /^Deposits received/ }).getByRole('link', { name })).toBeVisible()
    expect(await axe(other.page, 'main')).toEqual([])
    expect(await other.page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await other.close()
  }

  // Handled: it waits no more.
  await call(page, `/api/v1/labs/${deposit.lab}/deposits/${deposit.id}/start-check/`, {})
  await call(page, `/api/v1/labs/${deposit.lab}/deposits/${deposit.id}/reject/`, { reason: 'End of the Home test.' })
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 2, name: /^Waiting for you/ })).toBeVisible()
  await expect(page.getByRole('region', { name: /^Waiting for you/ }).getByRole('link', { name, exact: true })).toHaveCount(0)
  expect(violations()).toEqual([])
  await close()
})

test("a viewer's Home shows the lab and no actions", async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-viewer')
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'My labs' }).getByRole('article', { name: 'E2E lab' })).toContainText('Viewer')
  await expect(page.getByRole('region', { name: 'Recent activity' })).toBeVisible()
  await expect(page.getByText('Nothing waits for you.')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Quick actions' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /^(Receive a deposit|Record a check|Find a vial|Enter a request)/ })).toHaveCount(0)
  // What only curators count is not there at all.
  await expect(page.getByRole('link', { name: /^Deposits to check|^Requests to decide/ })).toHaveCount(0)
  expect(await axe(page, 'main')).toEqual([])
  await close()
})
