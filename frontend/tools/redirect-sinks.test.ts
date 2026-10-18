import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

// Invariant: every place that sends the browser somewhere takes its target from safeRedirect
// (paths) or safeHref (links). oxlint 1.88 has no no-restricted-syntax rule, so this test reads
// the source with the TypeScript parser instead. Sinks:
//   - redirect({ href }), navigate({ href }), x.navigate({ href }): href is safeRedirect(...)
//   - the same calls with search: { redirect }: the value is safeRedirect(...)
//   - history.push(x), history.replace(x), location.assign(x), location.replace(x): x is safeRedirect(...)
//   - assigning to location, window.location or location.href: never
//   - a JSX href: a string literal, a template literal that starts with #, or safeHref(...)
const frontend = resolve(import.meta.dirname, '..')

type Site = { file: string; line: number; sink: string; ok: boolean; text: string }

const NAVIGATIONS = new Set(['redirect', 'navigate'])
const PATH_SINKS = new Set(['history.push', 'history.replace', 'location.assign', 'location.replace'])

function calleeName(expression: ts.Expression): string {
  if (ts.isIdentifier(expression)) return expression.text
  if (ts.isPropertyAccessExpression(expression)) {
    const object = expression.expression
    const owner = ts.isPropertyAccessExpression(object) ? object.name.text : ts.isIdentifier(object) ? object.text : ''
    return `${owner}.${expression.name.text}`
  }
  return ''
}

const isCallTo = (node: ts.Node, name: string) => ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === name

function property(object: ts.ObjectLiteralExpression, name: string): ts.Expression | undefined {
  for (const p of object.properties) {
    if (ts.isPropertyAssignment(p) && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) && p.name.text === name) return p.initializer
    if (ts.isShorthandPropertyAssignment(p) && p.name.text === name) return p.name
  }
  return undefined
}

const isLocation = (node: ts.Expression) =>
  (ts.isIdentifier(node) && node.text === 'location') ||
  (ts.isPropertyAccessExpression(node) && node.name.text === 'location' && ts.isIdentifier(node.expression) && node.expression.text === 'window')

/** Every redirect sink in one source text, each with whether it passes. */
function redirectSinks(file: string, source: string): Site[] {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, file.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const sites: Site[] = []
  const add = (node: ts.Node, sink: string, ok: boolean) =>
    sites.push({ file, line: sf.getLineAndCharacterOfPosition(node.getStart()).line + 1, sink, ok, text: node.getText() })

  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node)) {
      const name = calleeName(node.expression)
      const method = name.includes('.') ? name.slice(name.indexOf('.') + 1) : name
      const [first] = node.arguments
      if (NAVIGATIONS.has(method) && first && ts.isObjectLiteralExpression(first)) {
        const href = property(first, 'href')
        if (href) add(href, `${name}({ href })`, isCallTo(href, 'safeRedirect'))
        const search = property(first, 'search')
        const target = search && ts.isObjectLiteralExpression(search) ? property(search, 'redirect') : undefined
        if (target) add(target, `${name}({ search: { redirect } })`, isCallTo(target, 'safeRedirect'))
      }
      if (PATH_SINKS.has(name)) add(node, name, first !== undefined && isCallTo(first, 'safeRedirect'))
    }
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      const left = node.left
      if (isLocation(left) || (ts.isPropertyAccessExpression(left) && left.name.text === 'href' && isLocation(left.expression)))
        add(node, 'location assignment', false)
    }
    if (ts.isJsxAttribute(node) && ts.isIdentifier(node.name) && node.name.text === 'href') {
      const init = node.initializer
      const value = init && ts.isJsxExpression(init) ? init.expression : init
      const ok =
        value !== undefined &&
        (ts.isStringLiteral(value) ||
          (ts.isNoSubstitutionTemplateLiteral(value) && value.text.startsWith('#')) ||
          (ts.isTemplateExpression(value) && value.head.text.startsWith('#')) ||
          isCallTo(value, 'safeHref'))
      add(node, 'JSX href', ok)
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return sites
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return entry.name === 'test' || entry.name === 'api' ? [] : sourceFiles(path)
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : []
  })
}

const sites = sourceFiles(join(frontend, 'src')).flatMap((path) => redirectSinks(relative(frontend, path), readFileSync(path, 'utf8')))

describe('redirect sinks (invariant)', () => {
  it('finds the known sinks, so an empty walk cannot pass', () => {
    const found = sites.map((s) => `${s.file} ${s.sink}`)
    expect(found).toEqual(
      expect.arrayContaining([
        'src/routes/login.tsx redirect({ href })',
        'src/pages/LoginPage.tsx navigate({ href })',
        'src/app/session.ts router.navigate({ search: { redirect } })',
        'src/routes/authenticated.tsx redirect({ search: { redirect } })',
        'src/components/ui/SkipLink.tsx JSX href',
      ]),
    )
  })

  it('takes every redirect target from safeRedirect and every href from safeHref', () => {
    expect(sites.filter((s) => !s.ok)).toEqual([])
  })
})

describe('redirect sink checker', () => {
  it.each([
    ['throw redirect({ href: search.redirect })', 'redirect({ href })'],
    ["void navigate({ href: raw, replace: true })", 'navigate({ href })'],
    ['void navigate({ href })', 'navigate({ href })'],
    ["void router.navigate({ to: '/login', search: { redirect: href } })", 'router.navigate({ search: { redirect } })'],
    ["throw redirect({ to: '/login', search: { redirect: location.href } })", 'redirect({ search: { redirect } })'],
    ['router.history.push(raw)', 'history.push'],
    ['window.location.assign(raw)', 'location.assign'],
    ['location.replace(raw)', 'location.replace'],
    ['window.location.href = raw', 'location assignment'],
    ['window.location = raw', 'location assignment'],
    ['location.href = safeRedirect(raw)', 'location assignment'],
  ])('refuses %s', (code, sink) => {
    expect(redirectSinks('probe.ts', code)).toEqual([expect.objectContaining({ sink, ok: false })])
  })

  it.each([
    ['const a = <a href={raw}>x</a>', 'JSX href'],
    ['const a = <a href={`${raw}`}>x</a>', 'JSX href'],
    ['const a = <a href={safeRedirect(raw)}>x</a>', 'JSX href'],
  ])('refuses %s', (code, sink) => {
    expect(redirectSinks('probe.tsx', code)).toEqual([expect.objectContaining({ sink, ok: false })])
  })

  it.each([
    ['throw redirect({ href: safeRedirect(search.redirect) })', 'redirect({ href })'],
    ["void router.navigate({ to: '/login', search: { redirect: safeRedirect(href) } })", 'router.navigate({ search: { redirect } })'],
    ['router.history.push(safeRedirect(raw))', 'history.push'],
  ])('accepts %s', (code, sink) => {
    expect(redirectSinks('probe.ts', code)).toEqual([expect.objectContaining({ sink, ok: true })])
  })

  it.each(['const a = <a href="#main">x</a>', 'const a = <a href={`#${id}`}>x</a>', 'const a = <a href={safeHref(raw)}>x</a>'])('accepts %s', (code) => {
    expect(redirectSinks('probe.tsx', code)).toEqual([expect.objectContaining({ sink: 'JSX href', ok: true })])
  })

  it('leaves reads of the location and typed navigation alone', () => {
    const code = "const o = window.location.origin\nwindow.location.reload()\nvoid navigate({ to: '/labs', search: { offset: 0 } })"
    expect(redirectSinks('probe.ts', code)).toEqual([])
  })
})
