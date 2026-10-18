import { type Browser, type BrowserContext, expect, type Locator, type Page, test } from '@playwright/test'
import { axe, password, ratio, ring, surfaceOf, tabTo, username, watchCsp } from './support.js'

// Checks that need a browser: reflow at 320 px (WCAG 1.4.10), the focus ring and its contrast
// (2.4.7, 1.4.11; axe does not test focus rings), titles and focus after navigation (2.4.2,
// 2.4.3), and a keyboard walk through every page. Nothing here changes data, so it runs next to
// labs.spec.ts. One sign-in for the whole file: the login throttle allows 10 a minute.

type State = Awaited<ReturnType<BrowserContext['storageState']>>
let signedIn: State

test.beforeAll(async ({ browser }) => {
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto('/login')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
  signedIn = await context.storageState()
  await context.close()
})

async function open(browser: Browser, options: { width?: number; colorScheme?: 'light' | 'dark'; anonymous?: boolean } = {}) {
  const context = await browser.newContext({
    storageState: options.anonymous ? undefined : signedIn,
    viewport: { width: options.width ?? 1280, height: options.width ? 640 : 720 },
    colorScheme: options.colorScheme ?? 'light',
  })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/**
 * The seeded lab has one member, too few for a pager. For the pager's checks the member list
 * answers with a larger count, so `?limit=1` shows Previous and Next without adding members
 * that labs.spec.ts would see. The rows are the real ones, cut to the signed-in user: labs.spec.ts
 * adds and removes e2e-colleague at the same time, and that row would otherwise come first.
 */
async function pretendMembers(page: Page, count: number) {
  await page.route('**/api/v1/labs/*/members/?*', async (route) => {
    // Every page shows the signed-in user's row, whatever limit and offset were asked for.
    const url = new URL(route.request().url())
    url.searchParams.delete('limit')
    url.searchParams.delete('offset')
    try {
      const response = await route.fetch({ url: url.toString() })
      const body: unknown = await response.json()
      const rows: unknown = typeof body === 'object' && body !== null ? Reflect.get(body, 'results') : []
      const own = Array.isArray(rows) ? rows.filter((row: unknown) => typeof row === 'object' && row !== null && Reflect.get(row, 'username') === username) : []
      await route.fulfill({ response, json: { count, next: null, previous: null, results: own } })
    } catch {
      // The page navigated away while the request ran (a preload on hover): nothing to answer.
    }
  })
}

/** From the labs list to the seeded lab, with an optional search (?limit=1 shows the pager). */
async function openLab(page: Page, search = '') {
  await page.goto('/labs')
  const link = page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' })
  const href = await link.getAttribute('href')
  await page.goto(`${href ?? ''}${search}`)
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
}

const fitsWidth = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth)

test.describe('reflow at 320 px', () => {
  test('login, labs, a lab, its dialog and the account menu fit without scrolling sideways, and pass axe', async ({ browser }) => {
    const anonymous = await open(browser, { width: 320, anonymous: true })
    const violationsLogin = await watchCsp(anonymous.page)
    await anonymous.page.goto('/login')
    await expect(anonymous.page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    expect(await fitsWidth(anonymous.page)).toBeLessThanOrEqual(320)
    expect(await axe(anonymous.page, 'body')).toEqual([])
    expect(violationsLogin()).toEqual([])
    await anonymous.close()

    const { page, close } = await open(browser, { width: 320 })
    const violations = await watchCsp(page)
    await page.goto('/labs')
    await expect(page.getByRole('heading', { level: 1, name: 'Labs' })).toBeVisible()
    // The user and sign-out live in the menu here.
    const account = page.getByRole('button', { name: `Account (${username})` })
    await expect(account).toBeVisible()
    await expect(page.getByText(`Signed in as ${username}`)).toHaveCount(0)
    expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
    // Fitting by squeezing is no fit: every control in the bar shows all of its text, inside the screen.
    const cut = await page.getByRole('banner').evaluate((bar) =>
      [...bar.querySelectorAll<HTMLElement>('a, button')]
        .filter((control) => {
          const box = control.getBoundingClientRect()
          const clipped = [control, ...control.querySelectorAll<HTMLElement>('*')].some((e) => e.scrollWidth > e.clientWidth)
          return clipped || box.left < 0 || box.right > 320
        })
        .map((control) => control.textContent),
    )
    expect(cut).toEqual([])
    // Today's two links fit anyway: with more of them the nav wraps instead of widening the page.
    await page.getByRole('navigation', { name: 'Main' }).evaluate((nav) => {
      const link = nav.querySelector('a')
      if (link) for (let i = 0; i < 6; i++) nav.append(link.cloneNode(true))
    })
    expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
    await page.reload()
    await expect(page.getByRole('heading', { level: 1, name: 'Labs' })).toBeVisible()
    expect(await axe(page, 'body')).toEqual([])

    await openLab(page)
    expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
    expect(await axe(page, 'body')).toEqual([])
    // The members table is wider than the screen: it scrolls inside its own container.
    const scroller = page.getByRole('table', { name: 'Members' }).locator('xpath=..')
    const sizes = await scroller.evaluate((e) => ({ scroll: e.scrollWidth, client: e.clientWidth, overflow: getComputedStyle(e).overflowX }))
    expect(sizes.overflow).toBe('auto')
    expect(sizes.scroll).toBeGreaterThan(sizes.client)
    // A long name without spaces wraps instead of widening the page.
    await page.getByRole('heading', { level: 1 }).evaluate((h) => {
      h.textContent = 'Mycology'.repeat(20)
    })
    expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
    await page.reload()

    await page.getByRole('button', { name: `Remove ${username}` }).click()
    const dialog = page.getByRole('alertdialog', { name: `Remove ${username}?` })
    await expect(dialog).toBeVisible()
    expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
    expect(await axe(page, '[role="alertdialog"]')).toEqual([])
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()

    await account.click()
    const menu = page.getByRole('menu', { name: `Account (${username})` })
    await expect(menu.getByRole('menuitem', { name: 'Sign out' })).toBeFocused()
    expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
    expect(await axe(page, '[role="menu"]')).toEqual([])
    await page.keyboard.press('Escape')
    await expect(account).toBeFocused()
    expect(violations()).toEqual([])
    await close()
  })
})

/**
 * A ring 2px solid, with 3:1 against the surface the control sits on (an outset ring; WCAG
 * 1.4.11 asks for contrast with the adjacent colour). The measured ratio goes into the report.
 */
async function expectRing(control: Locator, what: string, surface?: string) {
  const drawn = await ring(control)
  expect(drawn.style, what).toBe('solid')
  expect(drawn.width, what).toBe('2px')
  const behind = surface ?? (await surfaceOf(control))
  const measured = ratio(drawn.color, behind)
  test.info().annotations.push({ type: 'focus ring', description: `${what}: ${drawn.color} on ${behind} = ${measured.toFixed(2)}:1` })
  expect(measured, `${what}: ring ${drawn.color} on ${behind}`).toBeGreaterThanOrEqual(3)
}

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`focus rings in the ${colorScheme} scheme`, () => {
    test('buttons and links on the bar, the paper and the page show a 2px ring with 3:1', async ({ browser }) => {
      const { page, close } = await open(browser, { colorScheme })
      await pretendMembers(page, 3)
      await openLab(page, '?limit=1')
      expect(await page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches)).toBe(colorScheme === 'dark')

      const skip = page.getByRole('link', { name: 'Skip to content' })
      await tabTo(page, skip)
      // Positioned over the bar, not inside it: measured against the bar and against its own paper.
      await expectRing(skip, 'skip link over the bar', await surfaceOf(page.getByRole('banner'), true))
      await expectRing(skip, 'skip link on its own paper', await surfaceOf(skip, true))
      const home = page.getByRole('link', { name: 'Culture collection' })
      await tabTo(page, home)
      await expectRing(home, 'title link on the bar')
      const signOut = page.getByRole('button', { name: 'Sign out' })
      await tabTo(page, signOut)
      await expectRing(signOut, 'Sign out on the bar')
      const labs = page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Labs' })
      await tabTo(page, labs)
      await expectRing(labs, 'Labs link on the bar')

      const next = page.getByRole('navigation', { name: 'Member pages' }).getByRole('button', { name: 'Next' })
      await tabTo(page, next)
      await expectRing(next, 'Next on the page')
      const remove = page.getByRole('button', { name: `Remove ${username}` })
      await tabTo(page, remove)
      await expectRing(remove, 'Remove in the table')

      // A text field shows focus as a 2px border in the primary colour.
      const field = page.getByRole('form', { name: 'Add a member' }).getByRole('textbox', { name: 'Username' })
      await tabTo(page, field)
      const border = await field.evaluate((input) => {
        const outline = input.parentElement?.querySelector('fieldset')
        const style = outline ? getComputedStyle(outline) : undefined
        return { width: style?.borderTopWidth, color: style?.borderTopColor ?? '' }
      })
      expect(border.width).toBe('2px')
      const fieldRatio = ratio(border.color, await surfaceOf(field))
      test.info().annotations.push({ type: 'focus ring', description: `text field border: ${border.color} = ${fieldRatio.toFixed(2)}:1` })
      expect(fieldRatio).toBeGreaterThanOrEqual(3)

      // In the dialog, on its paper (lighter in the dark scheme).
      await page.keyboard.press('Escape')
      await remove.focus()
      await page.keyboard.press('Enter')
      const dialog = page.getByRole('alertdialog')
      const cancel = dialog.getByRole('button', { name: 'Cancel' })
      const confirm = dialog.getByRole('button', { name: 'Remove' })
      await expect(cancel).toBeFocused()
      await page.keyboard.press('Tab')
      await expect(confirm).toBeFocused()
      await expectRing(confirm, 'Remove in the dialog')
      await page.keyboard.press('Shift+Tab')
      await expectRing(cancel, 'Cancel in the dialog')
      await page.keyboard.press('Escape')
      await expect(remove).toBeFocused()

      // The table's link, on the list page.
      await page.goto('/labs')
      const lab = page.getByRole('link', { name: 'E2E lab' })
      await tabTo(page, lab)
      await expectRing(lab, 'lab link in the table')
      await close()
    })

    test('the account menu button and its item show a ring with 3:1 at 320 px', async ({ browser }) => {
      const { page, close } = await open(browser, { colorScheme, width: 320 })
      await page.goto('/')
      const account = page.getByRole('button', { name: `Account (${username})` })
      await tabTo(page, account)
      await expectRing(account, 'account menu button on the bar')
      await page.keyboard.press('Enter')
      const item = page.getByRole('menuitem', { name: 'Sign out' })
      await expect(item).toBeFocused()
      // MUI insets the ring inside a menu item (a scrolling list would clip it): it sits on the item.
      const drawn = await ring(item)
      expect(drawn.style).toBe('solid')
      expect(drawn.width).toBe('2px')
      const itemRatio = ratio(drawn.color, await surfaceOf(item, true))
      test.info().annotations.push({ type: 'focus ring', description: `menu item (inset): ${drawn.color} = ${itemRatio.toFixed(2)}:1` })
      expect(itemRatio).toBeGreaterThanOrEqual(3)
      await page.keyboard.press('Escape')
      await close()
    })
  })
}

test.describe('titles and focus after navigation', () => {
  test('the main navigation by keyboard: each page gets its title and its h1 the focus; the first load keeps focus where it was', async ({ browser }) => {
    const { page, close } = await open(browser)
    await page.goto('/')
    await expect(page).toHaveTitle('Home | Culture collection')
    await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
    expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true)

    // Tab from the start: skip link, the title link, then the main navigation.
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
    await page.keyboard.press('Tab')
    await page.keyboard.press('Tab')
    const nav = page.getByRole('navigation', { name: 'Main' })
    await expect(nav.getByRole('link', { name: 'Home' })).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(nav.getByRole('link', { name: 'Labs' })).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL('/labs')
    await expect(page).toHaveTitle('Labs | Culture collection')
    await expect(page.getByRole('heading', { level: 1, name: 'Labs' })).toBeFocused()

    // Tab from the h1 into the table, open the lab.
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'E2E lab' })).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page).toHaveTitle('E2E lab | Culture collection')
    await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeFocused()

    // Back in history is a path change too.
    await page.goBack()
    await expect(page.getByRole('heading', { level: 1, name: 'Labs' })).toBeFocused()
    // Shift+Tab from the h1 goes back to the bar's last control.
    await page.keyboard.press('Shift+Tab')
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeFocused()
    await nav.getByRole('link', { name: 'Home' }).press('Enter')
    await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeFocused()

    await page.goto('/no-such-page')
    await expect(page).toHaveTitle('Page not found | Culture collection')
    await close()
  })

  test('Next in the pager keeps the focus, also on the last page', async ({ browser }) => {
    const { page, close } = await open(browser)
    await pretendMembers(page, 2)
    await openLab(page, '?limit=1')
    const pager = page.getByRole('navigation', { name: 'Member pages' })
    const next = pager.getByRole('button', { name: 'Next' })
    await tabTo(page, next)
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/offset=1/)
    await expect(pager).toContainText('2 to 2 of')
    await expect(next).toBeFocused()
    await expect(next).toHaveAttribute('aria-disabled', 'true')
    await close()
  })
})

/** Focus stops from the top of the page until Tab leaves the document (the browser's own UI). */
async function walk(page: Page) {
  const stops: string[] = []
  await page.evaluate(() => {
    const active = document.activeElement
    if (active instanceof HTMLElement) active.blur()
  })
  for (let i = 0; i < 60; i++) {
    await page.keyboard.press('Tab')
    const stop = await page.evaluate(() => {
      const e = document.activeElement
      if (!e || e === document.body) return null
      const style = getComputedStyle(e)
      const fieldset = e.matches('input, select, textarea') ? e.parentElement?.querySelector('fieldset') : null
      const visible = style.outlineStyle !== 'none' && style.outlineWidth !== '0px' ? true : fieldset ? getComputedStyle(fieldset).borderTopWidth === '2px' : false
      const label = e.getAttribute('aria-label') ?? (e.textContent ?? '').trim()
      return { name: `${e.tagName.toLowerCase()}:${label}`, visible }
    })
    if (stop === null) break // past the last control: focus left the document
    expect(stop.visible, `focus indicator on ${stop.name}`).toBe(true)
    stops.push(stop.name)
  }
  expect(stops.length).toBeGreaterThan(0)
  expect(stops.length, 'Tab never leaves the page').toBeLessThan(60)
  return stops
}

// The keyboard walk: Tab through every page from the top. Each stop is a named control with a
// visible focus indicator, focus never falls to the body, and Tab never gets stuck.
test.describe('keyboard walk through every page', () => {
  test('every page has a named, visible stop for every control and none on the body', async ({ browser }) => {
    const anonymous = await open(browser, { anonymous: true })
    await anonymous.page.goto('/login')
    await expect(anonymous.page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    const login = await walk(anonymous.page)
    expect(login.slice(0, 5)).toEqual(['a:Skip to content', 'a:Culture collection', 'input:', 'input:', 'button:Sign in'])
    await anonymous.close()

    const { page, close } = await open(browser)
    await pretendMembers(page, 3)
    for (const path of ['/', '/labs']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      const stops = await walk(page)
      expect(stops.slice(0, 5), path).toEqual(['a:Skip to content', 'a:Culture collection', 'a:Home', 'a:Labs', 'button:Sign out'])
    }
    // An unknown URL loaded directly: the shell has not asked for the user yet, so no navigation.
    await page.goto('/no-such-page')
    await expect(page.getByRole('heading', { level: 1, name: 'Page not found' })).toBeVisible()
    expect(await walk(page)).toEqual(['a:Skip to content', 'a:Culture collection', 'a:Go to the start page'])
    await openLab(page, '?limit=1')
    const stops = await walk(page)
    // Every control of the lab page in reading order; Previous is aria-disabled, still a stop.
    expect(stops).toEqual([
      'a:Skip to content',
      'a:Culture collection',
      'a:Home',
      'a:Labs',
      'button:Sign out',
      'a:Strains',
      `button:Change role of ${username}`,
      `button:Remove ${username}`,
      'button:Previous',
      'button:Next',
      'input:',
      'select:ViewerTechnicianCuratorManager',
      'button:Add member',
    ])
    await close()
  })
})
