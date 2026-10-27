import { type Browser, expect, type Locator, type Page, test } from '@playwright/test'
import { axe, channels, ratio, ring, signedInAs, surfaceOf, tabTo, username, watchCsp } from './support.js'

// Each test walks several pages and scans them with axe: real work, 5 to 25 s on a quiet machine and over
// the 30 s default on a busy one (#60).
test.describe.configure({ timeout: 120_000 })

// Checks that need a browser: reflow at 320 px (WCAG 1.4.10), the focus ring and its contrast
// (2.4.7, 1.4.11; axe does not test focus rings), titles and focus after navigation (2.4.2,
// 2.4.3), and a keyboard walk through every page. Nothing here changes data, so it runs next to
// labs.spec.ts. It works as the session auth.setup.ts signed in.

async function open(browser: Browser, options: { width?: number; colorScheme?: 'light' | 'dark'; anonymous?: boolean } = {}) {
  const context = await browser.newContext({
    storageState: options.anonymous ? undefined : signedInAs(username),
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
    await page.reload()
    await expect(page.getByRole('heading', { level: 1, name: 'Labs' })).toBeVisible()
    expect(await axe(page, 'body')).toEqual([])

    await openLab(page)
    expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
    expect(await axe(page, 'body')).toEqual([])
    // The lab tabs do not widen the page: the row scrolls inside itself, and the active tab is in view.
    const tabs = page.getByRole('navigation', { name: 'Lab sections' })
    const row = await tabs.locator('a').first().locator('xpath=..').evaluate((e) => ({ scroll: e.scrollWidth, client: e.clientWidth, overflow: getComputedStyle(e).overflowX }))
    expect(row.overflow).toBe('auto')
    expect(row.scroll).toBeGreaterThan(row.client) // six tabs do not fit in 320 px
    for (const name of ['Strains', 'MTA templates']) {
      const tab = tabs.getByRole('link', { name })
      await tab.scrollIntoViewIfNeeded()
      await expect(tab).toBeInViewport()
      const box = await tab.boundingBox()
      expect(box?.height ?? 0, `${name} tab height`).toBeGreaterThanOrEqual(24)
    }
    expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
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
    await expect(menu.getByRole('menuitemradio', { name: 'System' })).toBeFocused()
    await expect(menu.getByRole('menuitem', { name: 'Sign out' })).toBeVisible()
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
      const home = page.getByRole('link', { name: 'Culture Collection' })
      await tabTo(page, home)
      await expectRing(home, 'title link on the bar')
      const picker = page.getByRole('button', { name: /^(Lab|Select a lab)/ })
      await tabTo(page, picker)
      await expectRing(picker, 'lab picker on the bar')
      // The search field (#76): a 2px border in the primary colour, on the bar.
      const search = page.getByRole('banner').getByRole('combobox', { name: 'Search' })
      await tabTo(page, search)
      const searchBorder = await search.evaluate((input) => {
        const style = getComputedStyle(input.parentElement?.querySelector('fieldset') ?? input)
        return { width: style.borderTopWidth, color: style.borderTopColor }
      })
      expect(searchBorder.width).toBe('2px')
      const searchRatio = ratio(searchBorder.color, await surfaceOf(search))
      test.info().annotations.push({ type: 'focus ring', description: `search field border: ${searchBorder.color} = ${searchRatio.toFixed(2)}:1` })
      expect(searchRatio).toBeGreaterThanOrEqual(3)
      const account = page.getByRole('button', { name: `Account (${username})` })
      await tabTo(page, account)
      await expectRing(account, 'account menu on the bar')
      // The tab's ring sits inside it: the row scrolls and would clip a ring outside.
      const strainsTab = page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains' })
      await tabTo(page, strainsTab)
      await expectRing(strainsTab, 'lab tab', await surfaceOf(strainsTab, true))

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

      // A storage tree item: the ring sits inside its row, on the page.
      await lab.click()
      await page.getByRole('link', { name: 'Storage' }).click()
      const unit = page.getByRole('treeitem', { name: /^E2E freezer,/ })
      await tabTo(page, unit)
      const row = unit.locator('> div').first()
      await expectRing(row, 'tree item row', await surfaceOf(row, true))
      await close()
    })

    test('the account menu button and its item show a ring with 3:1 at 320 px', async ({ browser }) => {
      const { page, close } = await open(browser, { colorScheme, width: 320 })
      await page.goto('/')
      // The search is a button here (#76), on the bar like the account menu.
      const search = page.getByRole('banner').getByRole('button', { name: 'Search' })
      await tabTo(page, search)
      await expectRing(search, 'search button on the bar')
      const account = page.getByRole('button', { name: `Account (${username})` })
      await tabTo(page, account)
      await expectRing(account, 'account menu button on the bar')
      await page.keyboard.press('Enter')
      const item = page.getByRole('menuitemradio', { name: 'System' })
      await expect(item).toBeFocused()
      // MUI insets the ring inside a menu item (a scrolling list would clip it): it sits on the item.
      const drawn = await ring(item)
      expect(drawn.style).toBe('solid')
      expect(drawn.width).toBe('2px')
      // The checked item is tinted (translucent): the ring is seen against the tint over the menu's paper.
      const [tr = 0, tg = 0, tb = 0, ta = 1] = channels(await item.evaluate((e) => getComputedStyle(e).backgroundColor))
      const paper = channels(await surfaceOf(item))
      const tinted = [tr, tg, tb].map((c, i) => Math.round(c * ta + (paper[i] ?? 0) * (1 - ta)))
      const itemRatio = ratio(drawn.color, `rgb(${tinted.join(', ')})`)
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

    // Tab from the start: skip link, the title link, then the lab picker, which opens on the
    // checked lab or its first item; End reaches All labs.
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'Culture Collection' })).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: /^(Lab|Select a lab)/ })).toBeFocused()
    await page.keyboard.press('Enter')
    await page.keyboard.press('End')
    await expect(page.getByRole('menuitem', { name: 'All labs' })).toBeFocused()
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
    await expect(page.getByRole('button', { name: `Account (${username})` })).toBeFocused()
    await page.getByRole('link', { name: 'Culture Collection' }).press('Enter')
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

/**
 * Focus stops from the top of the page until Tab leaves the document (the browser's own UI).
 * MOST_STOPS is far above any page's controls: Home of the e2e user lists what every earlier run
 * left waiting (a link each, 20 per kind) and 20 lines of activity, and the bar has the search
 * field (#76), so a local stack after a few runs passed 60 stops with no trap.
 */
const MOST_STOPS = 150
async function walk(page: Page) {
  const stops: string[] = []
  await page.evaluate(() => {
    const active = document.activeElement
    if (active instanceof HTMLElement) active.blur()
  })
  for (let i = 0; i < MOST_STOPS; i++) {
    await page.keyboard.press('Tab')
    const stop = await page.evaluate(() => {
      const e = document.activeElement
      if (!e || e === document.body) return null
      // A tree item draws its ring around its own row, not around the units below it.
      const drawn = e.getAttribute('role') === 'treeitem' ? (e.firstElementChild ?? e) : e
      const style = getComputedStyle(drawn)
      const fieldset = e.matches('input, select, textarea') ? e.parentElement?.querySelector('fieldset') : null
      const visible = style.outlineStyle !== 'none' && style.outlineWidth !== '0px' ? true : fieldset ? getComputedStyle(fieldset).borderTopWidth === '2px' : false
      const labelledBy = e.getAttribute('aria-labelledby')
      const named = labelledBy ? document.getElementById(labelledBy)?.textContent : undefined
      // A lab tab names what waits after its name ("Requests, 3 to decide", #69): the count depends
      // on what the other specs leave waiting, so the stop is the tab's name.
      const label = (e.getAttribute('aria-label') ?? named ?? (e.textContent ?? '').trim()).replace(/, \d+ to (decide|check)$/, '')
      return { name: `${e.tagName.toLowerCase()}:${label}`, visible }
    })
    if (stop === null) break // past the last control: focus left the document
    expect(stop.visible, `focus indicator on ${stop.name}`).toBe(true)
    stops.push(stop.name)
  }
  expect(stops.length).toBeGreaterThan(0)
  expect(stops.length, 'Tab never leaves the page').toBeLessThan(MOST_STOPS)
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
    expect(login.slice(0, 5)).toEqual(['a:Skip to content', 'a:Culture Collection', 'input:', 'input:', 'button:Sign in'])
    await anonymous.close()

    const { page, close } = await open(browser)
    await pretendMembers(page, 3)
    for (const path of ['/', '/labs']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      const stops = await walk(page)
      // The search field (#76) sits between the lab picker and the account menu.
      expect(stops.slice(0, 5), path).toEqual(['a:Skip to content', 'a:Culture Collection', 'button:Select a lab', 'input:', `button:Account (${username})`])
    }
    // An unknown URL loaded directly: the shell has not asked for the user yet, so no navigation.
    await page.goto('/no-such-page')
    await expect(page.getByRole('heading', { level: 1, name: 'Page not found' })).toBeVisible()
    expect(await walk(page)).toEqual(['a:Skip to content', 'a:Culture Collection', 'a:Go to the start page'])
    await openLab(page, '?limit=1')
    const stops = await walk(page)
    // Every control of the lab page in reading order; Previous is aria-disabled, still a stop.
    expect(stops).toEqual([
      'a:Skip to content',
      'a:Culture Collection',
      'button:Lab E2E lab',
      'input:',
      `button:Account (${username})`,
      'a:Strains',
      'a:Storage',
      'a:Requests',
      'a:Deposits',
      'a:Depositors',
      'a:MTA templates',
      'a:Media',
      'a:Permits',
      `button:Change role of ${username}`,
      `button:Revoke regulated locations for ${username}`,
      `button:Remove ${username}`,
      'button:Previous',
      'button:Next',
      'input:',
      'select:ViewerTechnicianCuratorManager',
      'button:Add member',
    ])
    // The storage tree is one stop, on its first unit (seed_e2e's E2E freezer sorts first).
    // Loaded directly, like the pages above: the walk starts at the top of a fresh page.
    await page.goto((await page.getByRole('link', { name: 'Storage' }).getAttribute('href')) ?? '')
    await expect(page.getByRole('heading', { level: 1, name: 'Storage of E2E lab' })).toBeVisible()
    expect(await walk(page)).toEqual([
      'a:Skip to content',
      'a:Culture Collection',
      'button:Lab E2E lab',
      'input:',
      `button:Account (${username})`,
      'a:Strains',
      'a:Storage',
      'a:Requests',
      'a:Deposits',
      'a:Depositors',
      'a:MTA templates',
      'a:Media',
      'a:Permits',
      'button:Add a freezer or tank',
      'li:E2E freezer, freezer, -20\u00a0°C',
    ])
    // A box: the curator's actions, then the vial finder and the grid, one stop on its first
    // position (seed_e2e's Box 1 holds nothing, so the details of A1 have no link).
    const box1 = await page.evaluate(async () => {
      const lab = location.pathname.split('/')[2] ?? ''
      const units: { public_id: string; name: string; parent: string | null }[] = await (await fetch(`/api/v1/labs/${lab}/storage-units/`)).json()
      const under = (parent: string | null | undefined, name: string) => units.find((u) => u.parent === parent && u.name === name)
      const box = under(under(under(null, 'E2E freezer')?.public_id, 'Rack 1')?.public_id, 'Box 1')
      return `/labs/${lab}/storage/${box?.public_id ?? ''}`
    })
    await page.goto(box1)
    await expect(page.getByRole('grid', { name: 'Positions of Box 1' })).toBeVisible()
    expect(await walk(page)).toEqual([
      'a:Skip to content',
      'a:Culture Collection',
      'button:Lab E2E lab',
      'input:',
      `button:Account (${username})`,
      'a:Strains',
      'a:Storage',
      'a:Requests',
      'a:Deposits',
      'a:Depositors',
      'a:MTA templates',
      'a:Media',
      'a:Permits',
      'a:Storage of E2E lab',
      'a:E2E freezer',
      'a:Rack 1',
      'button:Change',
      'button:Move',
      'button:Put out of service',
      'button:Retire',
      'input:',
      'button:Find',
      'td:A1, empty',
    ])
    await close()
  })
})
