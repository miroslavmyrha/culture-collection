import { type Browser, type BrowserContext, expect, type Page, test } from '@playwright/test'
import { axe, password, username, watchCsp } from './support.js'

// The storage tree against the real API (seed_e2e: the e2e user manages "E2E lab", e2e-viewer
// views it, and two box types exist). Units are never deleted, so each run builds its own
// freezer, named uniquely per run, and finds it by that name. One sign-in per role for the
// whole file: the login throttle allows 10 a minute.

type State = Awaited<ReturnType<BrowserContext['storageState']>>
const signedIn: Record<string, State> = {}
const RUN = Date.now().toString(36)

async function signIn(browser: Browser, name: string) {
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto('/login')
  await page.getByLabel('Username').fill(name)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
  signedIn[name] = await context.storageState()
  await context.close()
}

test.beforeAll(async ({ browser }) => {
  await signIn(browser, username)
  await signIn(browser, 'e2e-viewer')
})

async function as(browser: Browser, name: string, width = 1280) {
  const context = await browser.newContext({ storageState: signedIn[name], viewport: { width, height: width === 320 ? 640 : 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/** From the labs list to the seeded lab's storage, by its links. */
async function openStorage(page: Page) {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await page.getByRole('link', { name: 'Storage' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Storage of E2E lab' })).toBeVisible()
}

/** A POST to the storage API from the page, with the session and its CSRF token. */
function postUnit(page: Page, body: Record<string, unknown>) {
  return page.evaluate(async (payload) => {
    await fetch('/api/v1/auth/csrf/')
    const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
    const lab = location.pathname.split('/')[2] ?? ''
    const response = await fetch(`/api/v1/labs/${lab}/storage-units/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) },
      body: JSON.stringify(payload),
    })
    return response.status
  }, body)
}

const fitsWidth = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth)

test('a manager builds a freezer, a rack and a box with the keyboard alone and finds them in the tree', async ({ browser }) => {
  const { page, close } = await as(browser, username)
  const violations = await watchCsp(page)
  await openStorage(page)
  const freezer = `Freezer e2e ${RUN}`

  // From here on only keys.
  await page.getByRole('button', { name: 'Add a freezer or tank' }).focus()
  await page.keyboard.press('Enter')
  let dialog = page.getByRole('dialog', { name: 'Add a freezer or tank' })
  const kind = dialog.getByRole('combobox', { name: 'Kind' })
  await expect(kind).toBeFocused()
  await expect(kind).toHaveValue('freezer')
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('textbox', { name: 'Name' })).toBeFocused()
  await page.keyboard.type(freezer)
  await page.keyboard.press('Tab')
  await page.keyboard.type('-80')
  await page.keyboard.press('Tab')
  const cap = dialog.getByRole('combobox', { name: 'Highest risk group' })
  await expect(cap).toBeFocused()
  await page.keyboard.type('Risk group 2') // a native select picks the option by its text
  await expect(cap).toHaveValue('2')
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('textbox', { name: 'Barcode' })).toBeFocused()
  await page.keyboard.press('Enter') // submits the form
  await expect(page.getByRole('heading', { level: 1, name: freezer })).toBeVisible()
  await expect(page).toHaveTitle(`${freezer} | Culture collection`)

  await page.getByRole('button', { name: 'Add a rack or box' }).focus()
  await page.keyboard.press('Enter')
  dialog = page.getByRole('dialog', { name: `Add a rack or box to ${freezer}` })
  await expect(dialog.getByRole('combobox', { name: 'Kind' })).toBeFocused()
  await expect(dialog.getByRole('combobox', { name: 'Kind' })).toHaveValue('rack')
  await page.keyboard.press('Tab')
  await page.keyboard.type('Rack 1')
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('textbox', { name: 'Slot' })).toBeFocused()
  await page.keyboard.type('1')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: 'Rack 1' })).toBeVisible()
  await expect(page).toHaveTitle(`Rack 1 in ${freezer} | Culture collection`)

  await page.getByRole('button', { name: 'Add a box' }).focus()
  await page.keyboard.press('Enter')
  dialog = page.getByRole('dialog', { name: 'Add a box to Rack 1' })
  await expect(dialog.getByRole('textbox', { name: 'Name' })).toBeFocused()
  await page.keyboard.type('Box 1')
  await page.keyboard.press('Tab')
  const type = dialog.getByRole('combobox', { name: 'Box type' })
  await expect(type).toBeFocused()
  await expect(type.getByRole('option', { name: '81-place cryobox (9 x 9)' })).toBeAttached()
  await page.keyboard.type('81')
  expect(await type.evaluate((select: HTMLSelectElement) => select.selectedOptions[0]?.textContent)).toBe('81-place cryobox (9 x 9)')
  await page.keyboard.press('Tab')
  await page.keyboard.type('1')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: 'Box 1' })).toBeVisible()
  await expect(page.locator('dd').filter({ hasText: '9 x 9, A1 to I9' })).toBeVisible()
  const crumbs = page.getByRole('navigation', { name: 'Breadcrumb' })
  await expect(crumbs).toHaveText(`Storage of E2E lab/${freezer}/Rack 1/Box 1`)

  // Back to the tree by the breadcrumb, and down to the box with the arrow keys.
  await crumbs.getByRole('link', { name: 'Storage of E2E lab' }).focus()
  await page.keyboard.press('Enter')
  const tree = page.getByRole('tree', { name: 'Storage of E2E lab' })
  const root = tree.getByRole('treeitem', { name: new RegExp(`^${freezer}, freezer, -80.°C$`) })
  await expect(root).toHaveAttribute('aria-expanded', 'true')
  await root.focus()
  await page.keyboard.press('ArrowDown')
  const rack = root.getByRole('treeitem', { name: 'Rack 1, rack in slot 1' })
  await expect(rack).toBeFocused()
  await expect(rack).toHaveAttribute('aria-expanded', 'false')
  await page.keyboard.press('ArrowRight')
  await expect(rack).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('ArrowDown')
  const box = rack.getByRole('treeitem', { name: 'Box 1, box in slot 1, 9 x 9' })
  await expect(box).toBeFocused()
  await expect(box).toHaveAttribute('aria-level', '3')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: 'Box 1' })).toBeVisible()
  expect(violations()).toEqual([])
  await close()
})

test('a viewer reads the storage but cannot change it, in the screen and at the API', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-viewer')
  await openStorage(page)
  await expect(page.getByText(/Arrow keys move|No storage yet/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add a freezer or tank' })).toHaveCount(0)
  // The server decides, not the hidden button.
  expect(await postUnit(page, { kind: 'freezer', name: `viewer ${RUN}`, max_risk_group: 1 })).toBe(403)
  await page.reload()
  await expect(page.getByRole('treeitem', { name: new RegExp(`viewer ${RUN}`) })).toHaveCount(0)
  await close()
})

test('the storage pages fit 320 px without scrolling sideways and pass axe', async ({ browser }) => {
  const { page, close } = await as(browser, username, 320)
  const violations = await watchCsp(page)
  await openStorage(page)
  expect(await postUnit(page, { kind: 'ln2_tank', name: `Tank e2e ${RUN}`, temperature_c: -196, max_risk_group: 1 })).toBe(201)
  await page.reload()
  const tank = page.getByRole('treeitem', { name: new RegExp(`^Tank e2e ${RUN}`) })
  await expect(tank).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  await tank.click()
  await expect(page.getByRole('heading', { level: 1, name: `Tank e2e ${RUN}` })).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  await page.getByRole('button', { name: 'Add a rack or box' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, '[role="dialog"]')).toEqual([])
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Add a rack or box' })).toBeFocused()
  await page.getByRole('button', { name: 'Retire' }).click()
  const retire = page.getByRole('alertdialog', { name: `Retire Tank e2e ${RUN}?` })
  await expect(retire.getByRole('button', { name: 'Cancel' })).toBeFocused()
  expect(await axe(page, '[role="alertdialog"]')).toEqual([])
  await page.keyboard.press('Escape')
  expect(violations()).toEqual([])
  await close()
})
