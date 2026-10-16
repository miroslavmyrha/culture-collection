import { execFileSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { afterAll, describe, expect, it } from 'vitest'

// Every boundary in .oxlintrc.json, proven by a probe file it must refuse, and one it must
// accept (so a config that refuses everything does not pass). Runs on a copy of the config in
// a temporary folder: nothing is written into src.
const frontend = resolve(import.meta.dirname, '..')
const oxlint = join(frontend, 'node_modules/.bin/oxlint')
const root = mkdtempSync(join(tmpdir(), 'lint-boundaries-'))
copyFileSync(join(frontend, '.oxlintrc.json'), join(root, '.oxlintrc.json'))
afterAll(() => rmSync(root, { recursive: true, force: true }))

function lint(file: string, specifier: string): { ok: boolean; output: string } {
  const path = join(root, file)
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, `import probe from '${specifier}'\nexport const used = probe\n`)
  try {
    const output = execFileSync(oxlint, ['-c', '.oxlintrc.json', '--deny-warnings', file], { cwd: root, encoding: 'utf8' })
    return { ok: true, output }
  } catch (error) {
    return { ok: false, output: String(Reflect.get(Object(error), 'stdout')) }
  } finally {
    rmSync(path)
  }
}

describe('import boundaries (invariant)', () => {
  it.each([
    ['src/features/a/x.ts', '@/features/b/api/queries', 'No feature-to-feature imports'],
    ['src/features/a/x.ts', '@/features/b', 'No feature-to-feature imports'],
    ['src/features/a/x.ts', '@/app/router', 'Features never import the app shell'],
    ['src/features/a/x.ts', '@/pages/HomePage', 'Features never import the app shell'],
    ['src/features/a/x.ts', '@/routes/login', 'Features never import the app shell'],
    ['src/features/a/deep/x.ts', '../../b/api/keys', 'Relative import leaves the feature'],
    ['src/features/a/x.ts', 'dompurify', 'Render HTML only through components/SafeHtml.tsx'],
    ['src/lib/x.ts', '@/features/a/api/keys', 'Shared code (lib, components, hooks)'],
    ['src/components/x.ts', '@/app/router', 'Shared code (lib, components, hooks)'],
    ['src/hooks/x.ts', '@/routes/login', 'Shared code (lib, components, hooks)'],
    ['src/lib/x.ts', 'dompurify', 'Render HTML only through components/SafeHtml.tsx'],
    ['src/pages/x.ts', '@/app/router', 'Pages compose features'],
    ['src/pages/x.ts', 'dompurify', 'Render HTML only through components/SafeHtml.tsx'],
    ['src/app/x.ts', 'dompurify', 'Render HTML only through components/SafeHtml.tsx'],
  ])('%s may not import %s', (file, specifier, message) => {
    const result = lint(file, specifier)
    expect(result.ok).toBe(false)
    expect(result.output).toContain(message)
  })

  it.each([
    ['src/features/a/x.ts', '@/lib/api'],
    ['src/features/a/x.ts', '@/components/Field'],
    ['src/features/a/deep/x.ts', '../api/keys'],
    ['src/pages/x.ts', '@/features/a/api/keys'],
    ['src/lib/sanitize.ts', 'dompurify'],
  ])('%s may import %s', (file, specifier) => {
    expect(lint(file, specifier)).toEqual({ ok: true, output: expect.any(String) })
  })
})
