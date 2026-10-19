import { type Browser, expect, type Locator, type Page, test } from '@playwright/test'
import { axe, ratio, ring, signedInAs, surfaceOf, tabTo, username, watchCsp } from './support.js'

// The box grid (#15) against the real API. seed_e2e: the B. subtilis strain has its passage 0,
// the regulated Testella exempli strain has two vials in E2E freezer > Rack 1 > Box R (A1, A2),
// e2e-user holds the lab's location grant, e2e-technician handles vials, e2e-viewer reads.
// Vials and units are never deleted, so each run preserves into a box of its own, named per run.
// It works as the sessions auth.setup.ts signed in.

const RUN = Date.now().toString(36)
type Scheme = 'light' | 'dark'

async function as(browser: Browser, name: string, options: { width?: number; colorScheme?: Scheme } = {}) {
  const width = options.width ?? 1280
  const context = await browser.newContext({
    storageState: signedInAs(name),
    viewport: { width, height: width === 320 ? 640 : 900 },
    colorScheme: options.colorScheme ?? 'light',
  })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/** The seeded lab's public id, from its link in the labs list. */
async function labOf(page: Page) {
  await page.goto('/labs')
  const href = await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).getAttribute('href')
  return (href ?? '').split('/')[2] ?? ''
}

/** A call to the lab's API from the page, with the session and its CSRF token: a GET, or a POST with a body. */
async function call(page: Page, lab: string, path: string, body?: Record<string, unknown>) {
  const answer = await page.evaluate(
    async ([labId, url, payload]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
      const target = url.startsWith('/') ? url : `/api/v1/labs/${labId}/${url}`
      const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) }
      const response = payload === undefined ? await fetch(target, { headers }) : await fetch(target, { method: 'POST', headers, body: JSON.stringify(payload) })
      return { status: response.status, text: await response.text() }
    },
    [lab, path, body] as const,
  )
  const json: unknown = JSON.parse(answer.text)
  return { ...answer, json }
}

type Row = Record<string, unknown>
const isRow = (value: unknown): value is Row => typeof value === 'object' && value !== null
/** The rows of a list answer, paged or not. */
const rows = (json: unknown): Row[] => {
  const list: unknown = isRow(json) && !Array.isArray(json) ? json.results : json
  return Array.isArray(list) ? list.filter(isRow) : []
}
const text = (row: unknown, key: string) => {
  const value: unknown = isRow(row) ? row[key] : undefined
  return typeof value === 'string' ? value : ''
}

/** A box of this run holding three vials of the B. subtilis strain in A1, A2 and A3, made by the manager. */
async function boxWithVials(browser: Browser, name: string) {
  const { page, close } = await as(browser, username)
  const lab = await labOf(page)
  const freezer = await call(page, lab, 'storage-units/', { kind: 'freezer', name: `Freezer g${RUN} ${name}`, max_risk_group: 1 })
  expect(freezer.status).toBe(201)
  const rack = await call(page, lab, 'storage-units/', { kind: 'rack', name: 'Rack 1', parent: text(freezer.json, 'public_id') })
  const types = await call(page, lab, '/api/v1/box-types/')
  const nine = text(rows(types.json).find((t) => text(t, 'name') === '81-place cryobox (9 x 9)'), 'public_id')
  const box = await call(page, lab, 'storage-units/', { kind: 'box', name, parent: text(rack.json, 'public_id'), box_type: nine })
  expect(box.status).toBe(201)
  const strains = await call(page, lab, `strains/?search=${encodeURIComponent('B. subtilis e2e seed')}`)
  const passages = await call(page, lab, `passages/?strain=${text(rows(strains.json)[0], 'public_id')}`)
  const batch = await call(page, lab, 'batches/', {
    passage: text(rows(passages.json).find((p) => p.number === 0), 'public_id'),
    method: 'cryo_minus80',
    purpose: 'distribution',
    preserved_on: '2026-10-01',
    vial_count: 3,
    box: text(box.json, 'public_id'),
  })
  expect(batch.status).toBe(201)
  await close()
  return { lab, box: text(box.json, 'public_id') }
}

/** The seeded Box R (two vials of the regulated strain), and every identity of those vials. */
async function boxR(page: Page) {
  const lab = await labOf(page)
  const units = rows((await call(page, lab, 'storage-units/')).json)
  const box = text(
    units.find((u) => u.kind === 'box' && u.name === 'Box R'),
    'public_id',
  )
  const strain = rows((await call(page, lab, `strains/?search=${encodeURIComponent('Testella exempli e2e regulated')}`)).json)[0]
  const vials = rows((await call(page, lab, `vials/?strain=${text(strain, 'public_id')}`)).json)
  const identities = [
    ...['public_id', 'accession_number', 'name_as_received'].map((key) => text(strain, key)),
    ...vials.flatMap((v) => ['public_id', 'label', 'batch'].map((key) => text(v, key))),
  ].filter((value) => value !== '')
  expect(identities).toHaveLength(9)
  return { lab, box, identities }
}

const grid = (page: Page, box: string) => page.getByRole('grid', { name: `Positions of ${box}` })
const cell = (page: Page, box: string, name: string | RegExp) => grid(page, box).getByRole('gridcell', { name })
const fitsWidth = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth)

test('a technician moves a vial by keyboard alone, and it stays there after a reload', async ({ browser }) => {
  const name = `Box k${RUN}`
  const { lab, box } = await boxWithVials(browser, name)
  const { page, close } = await as(browser, 'e2e-technician')
  const violations = await watchCsp(page)
  await page.goto(`/labs/${lab}/storage/${box}`)
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  const a1 = cell(page, name, /^A1, E2E \d+ \/ \d+ \/ 1, available$/)
  await expect(a1).toBeVisible()
  const label = ((await a1.getAttribute('aria-label')) ?? '').split(', ')[1] ?? ''

  // From here on only keys: Tab from the Find button enters the grid on its one stop.
  await tabTo(page, page.getByRole('button', { name: 'Find' }))
  await page.keyboard.press('Tab')
  await expect(a1).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(a1).toHaveAttribute('aria-selected', 'true')
  const status = page.getByRole('status')
  await expect(status).toHaveText(`${label} in A1 selected. Choose an empty position and press Enter, or Escape to cancel.`)
  const scrolled = await page.evaluate(() => window.scrollY)
  for (const key of ['ArrowDown', 'ArrowDown', 'ArrowRight', 'ArrowRight', 'ArrowRight']) await page.keyboard.press(key)
  expect(await page.evaluate(() => window.scrollY)).toBe(scrolled) // the arrows move focus, not the page
  await expect(cell(page, name, 'C4, empty')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(status).toHaveText(`${label} moved to C4.`)
  const moved = cell(page, name, `C4, ${label}, available`)
  await expect(moved).toBeFocused()
  await expect(cell(page, name, 'A1, empty')).toBeVisible()
  await expect(grid(page, name).locator('[aria-selected="true"]')).toHaveCount(0)

  // Escape cancels a second move and puts the focus back on the vial.
  await page.keyboard.press('Enter')
  await page.keyboard.press('PageDown')
  await page.keyboard.press('Escape')
  await expect(status).toHaveText('Move cancelled.')
  await expect(moved).toBeFocused()

  await page.reload()
  await expect(cell(page, name, `C4, ${label}, available`)).toBeVisible()
  await expect(cell(page, name, 'A1, empty')).toBeVisible()
  expect(violations()).toEqual([])
  await close()
})

test('a viewer reads a grid without selection or bench work, and the API refuses a move', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-viewer')
  const { lab, box } = await boxR(page)
  await page.goto(`/labs/${lab}/storage/${box}`)
  const g = grid(page, 'Box R')
  await expect(g).toHaveAttribute('aria-readonly', 'true')
  await expect(g.locator('[aria-selected], [aria-disabled]')).toHaveCount(0)
  await expect(page.getByRole('form', { name: 'Place a vial' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Find|Cancel move/ })).toHaveCount(0)
  const a1 = cell(page, 'Box R', 'A1, occupied, regulated')
  await a1.focus()
  await page.keyboard.press('Enter')
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('Space')
  await expect(page.getByRole('status')).toHaveText('')
  await expect(g.locator('[aria-selected]')).toHaveCount(0)
  // The server decides, not the missing controls.
  const vials = rows((await call(page, lab, 'vials/?limit=1')).json)
  const move = await call(page, lab, `vials/${text(vials[0], 'public_id')}/place/`, { box, row: 9, col: 9 })
  expect(move.status).toBe(403)
  await close()
})

test('a regulated vial is an occupied position with no identity, in the page and in the API, also for the grant holder', async ({ browser }) => {
  for (const user of [username, 'e2e-technician']) {
    const { page, close } = await as(browser, user)
    const { lab, box, identities } = await boxR(page)
    const answer = await call(page, lab, `boxes/${box}/`)
    for (const identity of identities) expect(answer.text, `${user}: API ${identity}`).not.toContain(identity)
    await page.goto(`/labs/${lab}/storage/${box}`)
    await expect(cell(page, 'Box R', 'A1, occupied, regulated')).toHaveText('Hidden')
    await expect(cell(page, 'Box R', 'A2, occupied, regulated')).toBeVisible()
    const html = await page.content()
    for (const identity of identities) expect(html, `${user}: page ${identity}`).not.toContain(identity)
    await expect(page.getByRole('button', { name: /Reveal/ })).toHaveCount(0)
    await cell(page, 'Box R', 'A1, occupied, regulated').focus()
    await expect(page.getByText('Position A1: a vial of a regulated strain. Which one is hidden.')).toBeVisible()
    await expect(page.getByRole('main').getByRole('link', { name: /^Strain / })).toHaveCount(0)
    if (user === 'e2e-technician') {
      // It cannot be picked here; its strain page moves it.
      await expect(cell(page, 'Box R', 'A1, occupied, regulated')).toHaveAttribute('aria-disabled', 'true')
      await page.keyboard.press('Enter')
      await expect(page.getByRole('status')).toHaveText('A1 holds a vial of a regulated strain. Move it from its strain page.')
      await expect(grid(page, 'Box R').locator('[aria-selected="true"]')).toHaveCount(0)
    }
    await close()
  }
})

test('the box page fits 320 px: the grid scrolls inside its own container, positions are 24 px or more, axe passes', async ({ browser }) => {
  const name = `Box n${RUN}`
  const { lab, box } = await boxWithVials(browser, name)
  const { page, close } = await as(browser, 'e2e-technician', { width: 320 })
  const violations = await watchCsp(page)
  await page.goto(`/labs/${lab}/storage/${box}`)
  const g = grid(page, name)
  await expect(g).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  const scroller = g.locator('xpath=..')
  const sizes = await scroller.evaluate((e) => ({ scroll: e.scrollWidth, client: e.clientWidth, overflow: getComputedStyle(e).overflowX }))
  expect(sizes.overflow).toBe('auto')
  expect(sizes.scroll).toBeGreaterThan(sizes.client)
  const smallest = await g.evaluate((table) =>
    [...table.querySelectorAll('[role="gridcell"]')].reduce((min, c) => {
      const r = c.getBoundingClientRect()
      return Math.min(min, r.width, r.height)
    }, Infinity),
  )
  expect(smallest).toBeGreaterThanOrEqual(24)
  // The last position scrolls into view when the arrows reach it, inside the container only.
  await cell(page, name, /^A1,/).focus()
  await page.keyboard.press('End')
  await expect(cell(page, name, 'A9, empty')).toBeFocused()
  expect(await scroller.evaluate((e) => e.scrollLeft)).toBeGreaterThan(0)
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  await page.keyboard.press('Home')
  await page.keyboard.press('Enter')
  await expect(cell(page, name, /^A1,/)).toHaveAttribute('aria-selected', 'true')
  expect(await axe(page, 'main')).toEqual([])
  expect(violations()).toEqual([])
  await close()
})

/**
 * The colour a cell is drawn with, as the eye sees it: its own background and every translucent
 * one under it (MUI's action.hover is black or white at 4 to 8 %), blended down to the first
 * opaque one. surfaceOf stops at the first background that is not fully transparent.
 */
const fill = (target: Locator) =>
  target.evaluate((start) => {
    // Inside evaluate on purpose: this function runs in the browser.
    // oxlint-disable-next-line unicorn/consistent-function-scoping
    const parse = (css: string) => (css.match(/[\d.]+/g) ?? []).map(Number)
    const layers: number[][] = []
    for (let node: Element | null = start; node; node = node.parentElement) {
      const [r = 0, g = 0, b = 0, a = 1] = parse(getComputedStyle(node).backgroundColor)
      if (a === 0) continue
      layers.push([r, g, b, a])
      if (a === 1) break
    }
    let [r, g, b] = [255, 255, 255]
    for (const [lr = 0, lg = 0, lb = 0, a = 1] of layers.toReversed()) [r, g, b] = [lr * a + r * (1 - a), lg * a + g * (1 - a), lb * a + b * (1 - a)]
    return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`
  })

for (const colorScheme of ['light', 'dark'] as const) {
  test(`grid states and rings have 3:1 or more in the ${colorScheme} scheme`, async ({ browser }) => {
    const name = `Box ${colorScheme[0]}${RUN}`
    const { lab, box } = await boxWithVials(browser, name)
    const { page, close } = await as(browser, 'e2e-technician', { colorScheme })
    await page.goto(`/labs/${lab}/storage/${box}`)
    const taken = cell(page, name, /^A1,/)
    const empty = cell(page, name, 'B1, empty')
    await expect(taken).toBeVisible()
    const paper = await surfaceOf(grid(page, name))
    const report = (what: string, value: number) => {
      test.info().annotations.push({ type: 'contrast', description: `${colorScheme} ${what}: ${value.toFixed(2)}:1` })
      expect(value, what).toBeGreaterThanOrEqual(3)
    }
    // Every position has a border that shows where it is.
    report('cell border on the paper', ratio(await empty.evaluate((e) => getComputedStyle(e).borderTopColor), paper))
    // A taken position says so in text; its fill only helps.
    report('taken text on its fill', ratio(await taken.evaluate((e) => getComputedStyle(e).color), await fill(taken)))

    await tabTo(page, page.getByRole('button', { name: 'Find' }))
    await page.keyboard.press('Tab')
    await expect(taken).toBeFocused()
    const ringOn = async (target: Locator, what: string) => {
      const drawn = await ring(target)
      expect(drawn.style, what).toBe('solid')
      expect(drawn.width, what).toBe('2px')
      report(`${what} ring`, ratio(drawn.color, await fill(target)))
    }
    await ringOn(taken, 'taken cell')
    await page.keyboard.press('ArrowDown')
    await ringOn(empty, 'empty cell')
    await page.keyboard.press('ArrowUp')
    await page.keyboard.press('Enter')
    await expect(taken).toHaveAttribute('aria-selected', 'true')
    const selectedFill = await fill(taken)
    report('selected fill on the paper', ratio(selectedFill, paper))
    report('selected fill next to an empty cell', ratio(selectedFill, await fill(empty)))
    report('selected text on its fill', ratio(await taken.evaluate((e) => getComputedStyle(e).color), selectedFill))
    await ringOn(taken, 'selected cell')
    expect(await axe(page, 'main')).toEqual([])
    await page.keyboard.press('Escape')
    await close()
  })
}
