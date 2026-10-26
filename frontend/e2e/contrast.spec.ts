import { type Browser, expect, type Locator, type Page, test } from '@playwright/test'
import { axe, channels, ratio, signedInAs, surfaceOf, tabTo, username } from './support.js'

// Each test walks several pages and scans them with axe: real work, 5 to 25 s on a quiet machine and over
// the 30 s default on a busy one (#60).
test.describe.configure({ timeout: 120_000 })

// Colours and target sizes as the browser draws them, in both schemes: text on hover and focus,
// links, the status chips, and axe on the shell. src/app/theme.test.ts checks the tokens; this
// checks what reaches the screen (a hover tint over a dialog's paper, a row's hover over a link).
// Nothing here changes data. It works as the session auth.setup.ts signed in.

async function open(browser: Browser, colorScheme: 'light' | 'dark', width = 1280) {
  const context = await browser.newContext({ storageState: signedInAs(username), viewport: { width, height: width < 600 ? 640 : 720 }, colorScheme })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

async function openLab(page: Page) {
  await page.goto('/labs')
  const href = await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).getAttribute('href')
  await page.goto(href ?? '')
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
}

const over = (top: string, under: string) => {
  const [r = 0, g = 0, b = 0, a = 1] = channels(top)
  const u = channels(under)
  return `rgb(${[r, g, b].map((c, i) => Math.round(c * a + (u[i] ?? 0) * (1 - a))).join(', ')})`
}

/** What an element is drawn on: its own and its ancestors' translucent backgrounds, blended down to the first opaque surface. */
async function drawnOn(element: Locator) {
  const layers = await element.evaluate((start) => {
    const out: string[] = []
    for (let node: Element | null = start; node; node = node.parentElement) {
      const color = getComputedStyle(node).backgroundColor
      const alpha = (color.match(/[\d.]+/g) ?? []).map(Number)[3] ?? 1
      if (alpha === 0) continue
      out.push(color)
      if (alpha === 1) break
    }
    return out
  })
  const last = layers.at(-1)
  const base = last !== undefined && (channels(last)[3] ?? 1) === 1 ? last : await surfaceOf(element, true)
  return layers.toReversed().reduce((under, layer) => over(layer, under), base)
}

async function textRatio(element: Locator, what: string, minimum = 4.5) {
  const color = await element.evaluate((e) => getComputedStyle(e).color)
  const behind = await drawnOn(element)
  const measured = ratio(color, behind)
  test.info().annotations.push({ type: 'contrast', description: `${what}: ${color} on ${behind} = ${measured.toFixed(2)}:1` })
  expect(measured, `${what}: ${color} on ${behind}`).toBeGreaterThanOrEqual(minimum)
}

/** Waits until the colour has stopped changing (MUI fades hover colours over 250 ms). */
async function settled(element: Locator) {
  let previous = ''
  await expect
    .poll(async () => {
      const now = await element.evaluate((e) => `${getComputedStyle(e).color}|${getComputedStyle(e).backgroundColor}`)
      const same = now === previous
      previous = now
      return same
    })
    .toBe(true)
}

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`${colorScheme} scheme`, () => {
    test('buttons keep 4.5:1 at rest, on hover and on focus, a hovered Cancel included', async ({ browser }) => {
      const { page, close } = await open(browser, colorScheme)
      await openLab(page)
      await page.getByRole('button', { name: `Remove ${username}` }).click()
      const dialog = page.getByRole('alertdialog')
      const cancel = dialog.getByRole('button', { name: 'Cancel' })
      const confirm = dialog.getByRole('button', { name: 'Remove' })
      await expect(cancel).toBeFocused()
      await settled(cancel)
      await textRatio(cancel, 'Cancel, focused')
      await confirm.hover()
      await settled(confirm)
      await textRatio(confirm, 'Remove, hovered')
      await cancel.hover()
      await settled(cancel)
      await textRatio(cancel, 'Cancel, hovered')
      await page.keyboard.press('Escape')
      await close()
    })

    test('links keep 4.5:1 at rest and on hover, on the page and in a hovered row', async ({ browser }) => {
      const { page, close } = await open(browser, colorScheme)
      await page.goto('/labs')
      const link = page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' })
      await page.mouse.move(0, 0)
      await settled(link)
      await textRatio(link, 'table link')
      await link.hover()
      await settled(link)
      await textRatio(link, 'table link, hovered (row and link)')
      await tabTo(page, link)
      await textRatio(link, 'table link, focused')
      await page.getByRole('link', { name: 'Skip to content' }).focus()
      await textRatio(page.getByRole('link', { name: 'Skip to content' }), 'skip link')
      await close()
    })

    test('the lab tabs read 4.5:1, the active one too, and every target on the shell is at least 24 by 24 px', async ({ browser }) => {
      const { page, close } = await open(browser, colorScheme)
      await openLab(page)
      const tabs = page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link')
      for (const tab of await tabs.all()) {
        await textRatio(tab, `tab ${await tab.innerText()}`)
        const box = await tab.boundingBox()
        expect(box?.height).toBeGreaterThanOrEqual(24)
        expect(box?.width).toBeGreaterThanOrEqual(24)
      }
      await page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains' }).click()
      const active = page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains' })
      await expect(active).toHaveAttribute('aria-current', 'page')
      await textRatio(active, 'active tab')
      for (const control of [page.getByRole('link', { name: 'Culture Collection' }), page.getByRole('button', { name: /^(Lab|Select a lab)/ }), page.getByRole('button', { name: `Account (${username})` })]) {
        const box = await control.boundingBox()
        expect(box?.height).toBeGreaterThanOrEqual(24)
        expect(box?.width).toBeGreaterThanOrEqual(24)
      }
      await close()
    })

    test('status chips on the strain list keep 4.5:1 text on their tint', async ({ browser }) => {
      const { page, close } = await open(browser, colorScheme)
      await openLab(page)
      await page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains' }).click()
      await expect(page.getByRole('heading', { level: 1, name: 'Strains' })).toBeVisible()
      const chips = page.locator('[data-tone]')
      await expect.poll(() => chips.count()).toBeGreaterThan(0)
      for (const chip of await chips.all()) await textRatio(chip, `chip ${await chip.getAttribute('data-tone')} ${await chip.innerText()}`)
      await close()
    })

    test('the shell passes axe on the home page and on a lab page', async ({ browser }) => {
      const { page, close } = await open(browser, colorScheme)
      await page.goto('/')
      await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
      expect(await axe(page, 'body')).toEqual([])
      await openLab(page)
      expect(await axe(page, 'body')).toEqual([])
      await page.getByRole('button', { name: `Account (${username})` }).click()
      await expect(page.getByRole('menuitemradio', { name: 'System' })).toBeVisible()
      expect(await axe(page, '[role="menu"]')).toEqual([])
      await close()
    })
  })
}

test('choosing a scheme in the account menu applies at once and stays across a reload; nothing is stored before a choice', async ({ browser }) => {
  const { page, close } = await open(browser, 'light')
  await page.goto('/')
  expect(await page.evaluate(() => localStorage.length)).toBe(0)
  await page.getByRole('button', { name: `Account (${username})` }).click()
  await page.getByRole('menuitemradio', { name: 'Dark' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-color-scheme', 'dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-color-scheme', 'dark')
  await close()
})
