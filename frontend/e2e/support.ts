import { AxeBuilder } from '@axe-core/playwright'
import { fileURLToPath } from 'node:url'
import { expect, type Locator, type Page } from '@playwright/test'

// Seeded by `python manage.py seed_e2e` (backend/cultures/labs/management/commands/seed_e2e.py),
// locally and in CI: the user manages the lab "E2E lab", e2e-curator and e2e-viewer are its curator
// and viewer, e2e-colleague is in no lab.
export const username = process.env.E2E_USERNAME ?? 'e2e-user'
export const password = process.env.E2E_PASSWORD ?? 'e2e correct horse battery'

/**
 * The users every spec works as. auth.setup.ts signs each in once per run and writes its session
 * to the file below, so the whole run stays under the login throttle (10 sign-ins a minute per
 * client). Only login.spec.ts signs in on its own, because sign-in is what it tests.
 */
export const signedInUsers = [username, 'e2e-curator', 'e2e-viewer']
export const signedInAs = (user: string) => fileURLToPath(new URL(`./.auth/${user}.json`, import.meta.url))

/**
 * Collects CSP and Trusted Types violations from every document the page loads: console errors
 * and securitypolicyviolation events. The binding sends each event to the test at once, so a
 * reload or goto does not drop what an earlier document reported (a window variable read at
 * the end only sees the last document). Chrome words Trusted Types errors as "requires
 * 'TrustedHTML' assignment", hence the wider pattern.
 */
export async function watchCsp(page: Page) {
  const seen: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error' && /Content Security Policy|Trusted ?(Type|HTML|Script)/i.test(msg.text())) seen.push(msg.text())
  })
  await page.exposeBinding('reportCspViolation', (_source, text: unknown) => {
    seen.push(String(text))
  })
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      const report: unknown = Reflect.get(window, 'reportCspViolation')
      if (typeof report === 'function') void report(`${e.effectiveDirective} ${e.blockedURI}`)
    })
  })
  return () => seen
}

/**
 * Axe on one part of the page, with the rules of WCAG 2.2 A and AA. It waits until no ancestor
 * is transparent: during MUI's fade-in axe cannot compute contrast and reports it as incomplete,
 * not as a violation, so a dialog checked too early passes with unreadable text.
 */
export async function axe(page: Page, selector: string) {
  const target = page.locator(selector)
  await expect
    .poll(() =>
      target.evaluate((element) => {
        let opacity = 1
        for (let node: Element | null = element; node; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity)
        return opacity
      }),
    )
    .toBe(1)
  const results = await new AxeBuilder({ page }).include(selector).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
  return results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)
}

export const channels = (css: string) => (css.match(/[\d.]+/g) ?? []).map(Number)
const linear = (c: number) => (c / 255 <= 0.04045 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4)
export const luminance = ([r = 0, g = 0, b = 0]: number[]) => 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)

/**
 * The WCAG contrast of a text's colour (blended over its surface when translucent) against the
 * surface's background. axe leaves contrast inside an MUI dialog as "incomplete" ("could not be
 * determined because it partially overlaps other elements", axe-core 4.13.0), so the dialog's
 * text is measured here.
 */
export async function contrast(text: Locator, surface: Locator) {
  const [fg = 0, fgG = 0, fgB = 0, alpha = 1] = channels(await text.evaluate((e) => getComputedStyle(e).color))
  const bg = channels(await surface.evaluate((e) => getComputedStyle(e).backgroundColor))
  const blended = [fg, fgG, fgB].map((c, i) => c * alpha + (bg[i] ?? 0) * (1 - alpha))
  const [light, dark] = [luminance(blended), luminance(bg)].toSorted((a, b) => b - a)
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05)
}

/** The WCAG contrast ratio of a colour (blended over the second when translucent) and an opaque one, both rgb() or rgba(). */
export function ratio(a: string, b: string) {
  const [r = 0, g = 0, bl = 0, alpha = 1] = channels(a)
  const under = channels(b)
  const blended = [r, g, bl].map((c, i) => c * alpha + (under[i] ?? 0) * (1 - alpha))
  const [light, dark] = [luminance(blended), luminance(under)].toSorted((x, y) => y - x)
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05)
}

/**
 * The colour an element is drawn on: the background of the nearest ancestor (or itself) that
 * has one. MUI's dark paper lightens with its elevation through a white gradient in
 * background-image (`--Paper-overlay`), not through background-color, so that overlay is
 * blended in: on a dialog it is what a ring next to the paper is seen against.
 */
export async function surfaceOf(element: Locator, includeSelf = false): Promise<string> {
  return element.evaluate((start, self) => {
    // Inside evaluate on purpose: this function runs in the browser.
    // oxlint-disable-next-line unicorn/consistent-function-scoping
    const parse = (css: string) => (css.match(/[\d.]+/g) ?? []).map(Number)
    for (let node: Element | null = self ? start : start.parentElement; node; node = node.parentElement) {
      const style = getComputedStyle(node)
      const [r = 0, g = 0, b = 0, a = 1] = parse(style.backgroundColor)
      if (a === 0) continue
      const overlay = /rgba\(255, 255, 255, ([\d.]+)\)/.exec(style.backgroundImage)
      const w = overlay ? Number(overlay[1]) : 0
      const mix = (c: number) => Math.round(c * (1 - w) + 255 * w)
      return `rgb(${mix(r)}, ${mix(g)}, ${mix(b)})`
    }
    return 'rgb(255, 255, 255)'
  }, includeSelf)
}

/** Focus an element the way a keyboard user does, so :focus-visible applies: from the one before it. */
export async function tabTo(page: Page, target: Locator) {
  await target.focus()
  await page.keyboard.press('Shift+Tab')
  await page.keyboard.press('Tab')
  await expect(target).toBeFocused()
}

/** The computed focus ring of the focused element. */
export async function ring(target: Locator) {
  return target.evaluate((e) => {
    const style = getComputedStyle(e)
    return { style: style.outlineStyle, width: style.outlineWidth, color: style.outlineColor, offset: style.outlineOffset }
  })
}
