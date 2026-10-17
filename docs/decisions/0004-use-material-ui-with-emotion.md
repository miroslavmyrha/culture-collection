# 0004 Use Material UI with emotion

Date: 2026-10-17
Status: accepted
Deciders: maintainer

## Context

Screens need a component library with accessible inputs, dialogs, menus and
later data grids and trees. ADR 0003 left the UI library open. The production
CSP allows styles only from our origin or with a per-response nonce, and
scripts only from our origin.

Considered (facts as of 2026-10-17, npm and GitHub):
- Material UI 9.5.0 with emotion: MUI released 2026-10-09, 17 releases in
  12 months, about 10 million downloads a week, 100+ commits in 90 days.
  Peer dependencies accept React 19. Emotion 11.14 is its default style
  engine: about 20 million downloads a week, but no release in 12 months and
  no commit in 90 days. Emotion inserts `<style>` elements at runtime, so its
  cache must carry the CSP nonce.
- Material UI with Pigment CSS (styles extracted at build time, no nonce
  needed): `@pigment-css/react` 0.0.31, one release in 12 months, no commit
  in 90 days, and its Vite plugin declares Vite up to 6 while we use Vite 8.
- Mantine, or shadcn/ui with Tailwind: a second design system to learn, and
  no data grid and tree on the level of MUI X.

## Decision

Use Material UI 9 with emotion. The emotion cache is created once with the
nonce from `<meta property="csp-nonce">`. Feature code imports MUI only
through `src/components/ui`, which re-exports what we use and wraps what
carries our decisions. Lint refuses `@mui/*` and `@emotion/*` elsewhere.

## Consequences

+ Accessible components, theming and later MUI X grid and tree from one
  vendor.
+ The CSP stays strict: no `'unsafe-inline'` for styles.
- Runtime style injection costs some render time, and emotion has had no
  release in a year.
- The nonce depends on the reverse proxy rewriting the placeholder per
  response. Without a proxy that can rewrite HTML, `style-src` would need
  `'unsafe-inline'`.

Fallback: stay on MUI and move to a build-time engine the MUI docs name,
without touching feature code, since only `components/ui` and `app/` import
MUI and emotion.

Revisit when: Pigment CSS (or MUI's successor engine) reaches 1.0 with
support for our Vite major, or emotion is declared unmaintained, or MUI 10
leaves alpha.
