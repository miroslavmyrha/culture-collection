import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// A lint or type suppression says why, so the next reader knows when it can go. oxlint takes
// the reason after " -- " on the same line. @ts-expect-error and @ts-ignore take it as the
// text after the directive (TypeScript has no separator).
const frontend = resolve(import.meta.dirname, '..')

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return files(path)
    return /\.(ts|tsx)$/.test(entry.name) ? [path] : []
  })
}

const DIRECTIVE = /(oxlint-disable[\w-]*|eslint-disable[\w-]*|@ts-expect-error|@ts-ignore)(.*)$/

describe('suppressions (invariant)', () => {
  it('every one in src and e2e states its reason', () => {
    const missing: string[] = []
    for (const file of [...files(join(frontend, 'src')), ...files(join(frontend, 'e2e'))]) {
      readFileSync(file, 'utf8')
        .split('\n')
        .forEach((line, index) => {
          if (!/^\s*(\/\/|\/\*|\*|\{\/\*)/.test(line)) return
          const match = DIRECTIVE.exec(line)
          if (!match) return
          const [, directive = '', rest = ''] = match
          const reason = directive.startsWith('@ts-') ? rest.trim() : (rest.split(' -- ')[1] ?? '').trim()
          if (reason === '') missing.push(`${file.slice(frontend.length + 1)}:${index + 1}`)
        })
    }
    expect(missing).toEqual([])
  })
})
