import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { runId } from '../e2e/run-id.ts'

// Spec files name their data with runId() from e2e/support.ts (#288): an id from the clock alone
// was taken by two files loaded in the same millisecond.
const e2e = resolve(import.meta.dirname, '..', 'e2e')

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return entry.name === '.auth' ? [] : files(path)
    return entry.name.endsWith('.ts') ? [path] : []
  })
}

/** Spec files that make an id from the clock themselves. */
export function clockIds(sources: Record<string, string>): string[] {
  return Object.entries(sources)
    .filter(([name, text]) => name !== 'run-id.ts' && /Date\.now\(\)\.toString\(36\)/.test(text))
    .map(([name]) => name)
}

describe('run ids of the e2e specs', () => {
  it('come from runId(), never from the clock in a spec file', () => {
    const sources = Object.fromEntries(files(e2e).map((path) => [relative(e2e, path), readFileSync(path, 'utf8')]))
    expect(Object.keys(sources).length).toBeGreaterThan(20)
    expect(clockIds(sources)).toEqual([])
  })

  it('names a spec that makes its own clock id', () => {
    expect(clockIds({ 'deposits.spec.ts': 'const RUN = Date.now().toString(36)', 'run-id.ts': 'Date.now().toString(36)' })).toEqual(['deposits.spec.ts'])
  })

  it('differ within one millisecond, and search finds them as typed', () => {
    const ids = Array.from({ length: 200 }, runId)
    expect(new Set(ids).size).toBe(ids.length)
    for (const id of ids) expect(id).toMatch(/^[0-9a-z]+$/)
  })
})
