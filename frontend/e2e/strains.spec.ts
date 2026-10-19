import { type Browser, type BrowserContext, expect, type Page, test } from '@playwright/test'
import { axe, password, watchCsp } from './support.js'

// The strain registry against the real API (seed_e2e: e2e-curator and e2e-viewer in "E2E lab",
// a few taxa, no permits). Real organisms appear only with facts that hold for them (B. subtilis
// is risk group 1; a lab strain may be a GMO); the permit gate is tried on the invented
// Testella exempli, so no real organism is entered with a legal status it does not have. Each run adds one strain: numbers are never reused and strains are
// never deleted, so the tests find theirs by a name made unique per run. One sign-in per role
// for the whole file: the login throttle allows 10 a minute.

type State = Awaited<ReturnType<BrowserContext['storageState']>>
const signedIn: Record<string, State> = {}
const RUN = Date.now().toString(36)

async function signIn(browser: Browser, username: string) {
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto('/login')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
  signedIn[username] = await context.storageState()
  await context.close()
}

test.beforeAll(async ({ browser }) => {
  await signIn(browser, 'e2e-curator')
  await signIn(browser, 'e2e-viewer')
})

async function as(browser: Browser, username: string, width = 1280) {
  const context = await browser.newContext({ storageState: signedIn[username], viewport: { width, height: width === 320 ? 640 : 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/** From the labs list to the seeded lab's strains, by its links. */
async function openStrains(page: Page) {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await page.getByRole('link', { name: 'Strains' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Strains of E2E lab' })).toBeVisible()
}

const fitsWidth = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth)

test('a curator adds a strain with the keyboard alone and finds it in the list and its detail', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator')
  const violations = await watchCsp(page)
  await openStrains(page)
  const add = page.getByRole('link', { name: 'Add a strain' })
  await add.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveTitle('Add a strain to E2E lab | Culture collection')
  const form = page.getByRole('form', { name: 'Add a strain' })

  // From here on only keys: Tab moves through the form in reading order.
  const taxon = form.getByRole('combobox', { name: 'Taxon' })
  await taxon.focus()
  await page.keyboard.type('subt')
  await expect(page.getByRole('option', { name: /Bacillus subtilis/ })).toBeVisible()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(taxon).toHaveValue('Bacillus subtilis (Ehrenberg 1835) Cohn 1872')
  await page.keyboard.press('Tab')
  await expect(form.getByRole('textbox', { name: 'Name as received' })).toBeFocused()
  await page.keyboard.type(`B. subtilis e2e ${RUN}`)
  await page.keyboard.press('Tab')
  await expect(form.getByRole('textbox', { name: 'Identified on' })).toBeFocused()
  await page.keyboard.press('Tab')
  await page.keyboard.type('16S rRNA gene sequence')
  await page.keyboard.press('Tab')
  const risk = form.getByRole('combobox', { name: 'Risk group' })
  await expect(risk).toBeFocused()
  await page.keyboard.type('1') // a native select picks the option by its text
  await expect(risk).toHaveValue('1')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(form.getByRole('textbox', { name: 'Isolation source' })).toBeFocused()
  await page.keyboard.type('garden soil')
  await page.keyboard.press('Tab')
  await page.keyboard.type('Czechia')
  await expect(form.getByRole('combobox', { name: 'Country of origin' })).toHaveValue('CZ')
  await page.keyboard.press('Tab')
  await page.keyboard.type('2019-05')
  await page.keyboard.press('Tab')
  await expect(form.getByRole('button', { name: 'Add a restriction' })).toBeFocused()
  await page.keyboard.press('Enter')
  const restriction = form.getByRole('group', { name: 'Restriction 1' })
  const kind = restriction.getByRole('combobox', { name: 'Kind' })
  await kind.focus()
  await page.keyboard.type('GMO')
  await expect(kind).toHaveValue('gmo')
  await page.keyboard.press('Tab')
  await page.keyboard.type(`Notification e2e ${RUN}`)
  await page.keyboard.press('Tab')
  const category = restriction.getByRole('combobox', { name: 'Contained use category' })
  await expect(category).toBeFocused()
  await page.keyboard.type('I')
  await expect(category).toHaveValue('1')
  await form.getByRole('button', { name: 'Add strain' }).focus()
  await page.keyboard.press('Enter')

  // The detail of the new strain: its number, its taxon, its history.
  const heading = page.getByRole('heading', { level: 1, name: /^E2E \d+$/ })
  await expect(heading).toBeVisible()
  const number = (await heading.textContent()) ?? ''
  await expect(page).toHaveTitle(`${number} | Culture collection`)
  await expect(page.getByText(`B. subtilis e2e ${RUN}`)).toBeVisible()
  await expect(page.getByRole('table', { name: 'Current restrictions' })).toContainText(`Notification e2e ${RUN}, category I`)
  await expect(page.getByRole('table', { name: 'Identification history' })).toContainText('Identification at accession')

  // In the list, found by its own name.
  await page.getByRole('link', { name: 'Strains of E2E lab' }).click()
  const search = page.getByRole('searchbox', { name: 'Number or name' })
  await search.fill(RUN)
  await search.press('Enter')
  await expect(page).toHaveURL(new RegExp(`search=${RUN}`))
  const row = page.getByRole('row', { name: new RegExp(RUN) })
  await expect(row.getByRole('link', { name: number })).toBeVisible()
  await expect(row).toContainText('GMO in contained use')
  expect(violations()).toEqual([])
  await close()
})

test('a VRAT strain is refused while the lab holds no SÚJB permit, and nothing is added', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator')
  await openStrains(page)
  await page.getByRole('link', { name: 'Add a strain' }).click()
  const form = page.getByRole('form', { name: 'Add a strain' })
  await form.getByRole('combobox', { name: 'Taxon' }).fill('exempli')
  await page.getByRole('option', { name: /Testella exempli/ }).click()
  await form.getByRole('textbox', { name: 'Name as received' }).fill(`refused ${RUN}`)
  await form.getByRole('textbox', { name: 'Identification method' }).fill('MALDI-TOF MS')
  await form.getByRole('combobox', { name: 'Risk group' }).selectOption('2')
  await form.getByRole('button', { name: 'Add a restriction' }).click()
  const kind = form.getByRole('group', { name: 'Restriction 1' }).getByRole('combobox', { name: 'Kind' })
  await kind.selectOption('cz_vrat')
  await form.getByRole('group', { name: 'Restriction 1' }).getByRole('textbox', { name: 'List entry' }).fill('Příloha 1, bod 2')
  await form.getByRole('button', { name: 'Add strain' }).click()
  await expect(kind).toHaveAttribute('aria-invalid', 'true')
  await expect(kind).toHaveAccessibleDescription(/no valid SÚJB permit for highly risky agents \(VRAT\)/)
  await expect(kind).toBeFocused()
  await page.goto(page.url().replace(/\/new$/, `?search=refused%20${RUN}`))
  await expect(page.getByText('No strain matches these filters.')).toBeVisible()
  await close()
})

test('a viewer reads strains but cannot add one, in the screen and at the API', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-viewer')
  await openStrains(page)
  await expect(page.getByRole('link', { name: 'Add a strain' })).toHaveCount(0)
  await page.goto(`${page.url()}/new`)
  await expect(page.getByText('Only curators and managers add strains.')).toBeVisible()
  await expect(page.getByRole('form', { name: 'Add a strain' })).toHaveCount(0)
  // The server decides, not the hidden link.
  const status = await page.evaluate(async () => {
    await fetch('/api/v1/auth/csrf/')
    const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
    const lab = location.pathname.split('/')[2] ?? ''
    const response = await fetch(`/api/v1/labs/${lab}/strains/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) },
      body: '{}',
    })
    return response.status
  })
  expect(status).toBe(403)
  await close()
})

test('the strain pages fit 320 px without scrolling sideways and pass axe', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator', 320)
  const violations = await watchCsp(page)
  await openStrains(page)
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  const first = page.getByRole('table', { name: 'Strains' }).getByRole('link').first()
  await first.click()
  await expect(page.getByRole('heading', { level: 2, name: 'Identification history' })).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  await page.getByRole('button', { name: 'Change risk group' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, '[role="dialog"]')).toEqual([])
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Change risk group' })).toBeFocused()
  await page.getByRole('link', { name: 'Strains of E2E lab' }).click()
  await page.getByRole('link', { name: 'Add a strain' }).click()
  await expect(page.getByRole('form', { name: 'Add a strain' })).toBeVisible()
  await page.getByRole('button', { name: 'Add a restriction' }).click()
  await page.getByRole('combobox', { name: 'Taxon' }).fill('bac')
  await expect(page.getByRole('listbox')).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  expect(violations()).toEqual([])
  await close()
})
