import { createTheme } from '@mui/material/styles'
import { describe, expect, it } from 'vitest'
import { schemes } from './theme'

// The tokens of the visual base, both schemes, computed from the theme itself: text 4.5:1 (WCAG
// 1.4.3), borders and rings 3:1 (1.4.11), on every surface and at rest, hover and selected. The
// browser measures the same on the rendered page (e2e/contrast.spec.ts); this runs in check.sh
// and fails the commit that changes a token.

type Rgb = readonly [number, number, number]
const parse = (css: string): { rgb: Rgb; alpha: number } => {
  if (css.startsWith('#')) {
    const n = Number.parseInt(css.slice(1), 16)
    return { rgb: [(n >> 16) & 255, (n >> 8) & 255, n & 255], alpha: 1 }
  }
  const [r = 0, g = 0, b = 0, a = 1] = (css.match(/[\d.]+/g) ?? []).map(Number)
  return { rgb: [r, g, b], alpha: a }
}
const over = (top: string, under: string): Rgb => {
  const { rgb, alpha } = parse(top)
  const base = parse(under).rgb
  const [r, g, b] = rgb
  const [br, bg, bb] = base
  return [r * alpha + br * (1 - alpha), g * alpha + bg * (1 - alpha), b * alpha + bb * (1 - alpha)]
}
const linear = (c: number) => (c / 255 <= 0.04045 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4)
const luminance = ([r, g, b]: Rgb) => 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
/** The contrast of `fg` (blended over `bg` when translucent) against `bg`. */
export function ratio(fg: string, bg: string) {
  const [light = 0, dark = 0] = [luminance(over(fg, bg)), luminance(parse(bg).rgb)].toSorted((a, b) => b - a)
  return (light + 0.05) / (dark + 0.05)
}
/** Names of the pairs below `min`, so a failure says which one. */
const below = (min: number, pairs: readonly (readonly [string, string, string])[]) =>
  pairs.filter(([, fg, bg]) => ratio(fg, bg) < min).map(([name, fg, bg]) => `${name}: ${fg} on ${bg} = ${ratio(fg, bg).toFixed(2)}`)

/** A colour over a surface as an opaque hex, for use as the next surface. */
const flatten = (top: string, under: string) => `rgb(${over(top, under).join(', ')})`

const apart = (a: string, b: string) => Math.min(Math.abs(hue(a) - hue(b)), 360 - Math.abs(hue(a) - hue(b)))
const hue = (css: string) => {
  const [r, g, b] = parse(css).rgb.map((c) => c / 255)
  const max = Math.max(r ?? 0, g ?? 0, b ?? 0)
  const d = max - Math.min(r ?? 0, g ?? 0, b ?? 0)
  if (d === 0) return 0
  const h = max === r ? (((g ?? 0) - (b ?? 0)) / d) % 6 : max === g ? ((b ?? 0) - (r ?? 0)) / d + 2 : ((r ?? 0) - (g ?? 0)) / d + 4
  return (h * 60 + 360) % 360
}

for (const scheme of ['light', 'dark'] as const) {
  // MUI fills in what the tokens leave out (hoverOpacity), as it does for the app.
  const p = createTheme({ palette: schemes[scheme] }).palette
  const surfaces = { page: p.background.default, paper: p.background.paper }
  // What a pointer over a table row or a text button paints on its surface.
  const rowHover = flatten(p.action.hover, p.background.paper)
  const buttonHover = flatten(`rgba(${parse(p.primary.main).rgb.join(',')},${p.action.hoverOpacity})`, p.background.paper)
  const outlinedHover = rowHover

  const errorHover = flatten(`rgba(${parse(p.error.main).rgb.join(',')},${p.action.hoverOpacity})`, p.background.paper)

  describe(`${scheme} scheme`, () => {
    it.each(Object.entries(surfaces))('text has 4.5:1 on the %s', (_name, surface) => {
      expect(
        below(4.5, [
          ['text', p.text.primary, surface],
          ['secondary text', p.text.secondary, surface],
          ['primary (text buttons, the active tab)', p.primary.main, surface],
          ['link', p.info.main, surface],
          ['link hover', p.info.dark, surface],
          ['error', p.error.main, surface],
          ['warning', p.warning.main, surface],
          ['success', p.success.main, surface],
        ]),
      ).toEqual([])
    })

    it('text and links keep 4.5:1 on a hovered row and a hovered text button', () => {
      expect(
        below(4.5, [
          ['text on a hovered row', p.text.primary, rowHover],
          ['secondary text on a hovered row', p.text.secondary, rowHover],
          ['link on a hovered row', p.info.main, rowHover],
          ['link hover on a hovered row', p.info.dark, rowHover],
          // The defect that started this: a hovered Cancel measured 4.38:1.
          ['hovered text button', p.primary.main, buttonHover],
          ['hovered danger text button', p.error.main, errorHover],
          ['hovered outlined button', p.text.primary, outlinedHover],
        ]),
      ).toEqual([])
    })

    it('contained buttons have 4.5:1 for their label, at rest and on hover', () => {
      const pairs = (['primary', 'error', 'warning', 'success', 'info'] as const).flatMap((tone) => [
        [`${tone} at rest`, p[tone].contrastText, p[tone].main] as const,
        [`${tone} hover`, p[tone].contrastText, p[tone].dark] as const,
      ])
      expect(below(4.5, pairs)).toEqual([])
    })

    it('control borders, the focus ring and the danger border have 3:1 on both surfaces', () => {
      const pairs = Object.values(surfaces).flatMap((surface) => [
        ['control border', p.controlBorder, surface] as const,
        ['focus ring and active tab', p.primary.main, surface] as const,
        ['danger border', p.error.main, surface] as const,
      ])
      expect(below(3, pairs)).toEqual([])
    })

    it.each(Object.entries(p.status))('the %s status chip has 4.5:1 for its text', (tone, colors) => {
      expect(below(4.5, [[tone, colors.fg, colors.bg]])).toEqual([])
    })

    it('the accent and the status colours are different colours', () => {
      for (const other of [p.error.main, p.warning.main, p.success.main, p.info.main]) expect(apart(p.primary.main, other)).toBeGreaterThanOrEqual(25)
    })
  })
}
