import { describe, expect, it } from 'vitest'
import { makeBatch, makeCheck, makePassage } from '@/test/factories'
import { batchStatusReason, checkDetails, emptyCheck, formatValue, kindsText, mayHold, mayRelease, notPassed, passageTree, sourceLabel } from './schemas'

const none = { identity: null, purity: null, viability: null } as const

describe('the release rule as the screen reads it (ADR 0008, D16)', () => {
  it.each([
    [none, ['identity', 'purity', 'viability']],
    [{ identity: 'pass', purity: 'reduced', viability: 'pass' }, []],
    [{ identity: 'pass', purity: 'fail', viability: 'pass' }, ['purity']],
    [{ identity: null, purity: 'pass', viability: 'fail' }, ['identity', 'viability']],
  ] as const)('%o has not passed %o', (latest, missing) => {
    expect(notPassed(makeBatch({ latest_checks: latest }))).toEqual(missing)
  })

  it('names one, two or three kinds', () => {
    expect(kindsText(['purity'])).toBe('purity')
    expect(kindsText(['identity', 'viability'])).toBe('identity and viability')
    expect(kindsText(['identity', 'purity', 'viability'])).toBe('identity, purity and viability')
    expect(kindsText([])).toBe('')
  })

  it('says why a batch is not released', () => {
    expect(batchStatusReason(makeBatch({ latest_checks: none }))).toBe('Waiting for a passed identity, purity and viability check.')
    expect(batchStatusReason(makeBatch({ latest_checks: { identity: 'pass', purity: 'pass', viability: 'reduced' } }))).toBe('All checks passed. A curator releases it.')
    expect(batchStatusReason(makeBatch({ status: 'on_hold', status_reason: 'A doubt.' }))).toBe('A doubt.')
  })

  it.each([
    ['pending_check', true, true, true],
    ['pending_check', false, false, true],
    ['on_hold', true, true, false],
    ['on_hold', false, false, false],
    ['released', true, false, true],
    ['exhausted', true, false, false],
  ] as const)('a %s batch, checks passed %s: release %s, hold %s', (status, passed, release, hold) => {
    const latest = passed ? ({ identity: 'pass', purity: 'pass', viability: 'pass' } as const) : none
    const batch = makeBatch({ status, latest_checks: latest })
    expect(mayRelease(batch)).toBe(release)
    expect(mayHold(batch)).toBe(hold)
  })
})

describe('a check as it reads', () => {
  it('drops the trailing zeros of a stored decimal', () => {
    expect(formatValue('250000000.0000')).toBe('250000000')
    expect(formatValue('12.5000')).toBe('12.5')
    expect(formatValue('100')).toBe('100')
    expect(formatValue('0.0000')).toBe('0')
  })

  it('reads method, value, vial, stage and person in one line', () => {
    expect(checkDetails(makeCheck({ method: 'other', method_detail: 'Flow cytometry', value: '87.5000', unit: 'percent', vial_label: 'MYC 42 / 1 / 2', stage: 'periodic' }))).toBe(
      'Other (Flow cytometry), 87.5 %, vial MYC 42 / 1 / 2, periodic, by technician',
    )
    expect(checkDetails(makeCheck())).toBe('Growth after revival, after preservation, by technician')
  })

  it('starts a new check with the first kind still waiting, after preservation when none exists', () => {
    expect(emptyCheck(makeBatch({ latest_checks: none }))).toMatchObject({ kind: 'identity', stage: 'after_preservation', method: 'morphology', result: 'pass' })
    expect(emptyCheck(makeBatch({ latest_checks: { identity: 'pass', purity: null, viability: 'pass' } }))).toMatchObject({ kind: 'purity', stage: 'periodic', method: 'streak_plate' })
    expect(emptyCheck(makeBatch({ latest_checks: { identity: 'pass', purity: 'pass', viability: 'pass' } }))).toMatchObject({ kind: 'viability', method: 'growth' })
  })
})

/** A tree as nested [number, children] pairs. */
const shape = (nodes: ReturnType<typeof passageTree>): unknown[] => nodes.map((n) => [n.passage.number, shape(n.children)])

describe('the passages as a tree from the deposit (#19)', () => {
  const zero = makePassage({ number: 0 })
  const one = makePassage({ number: 1, source_kind: 'passage', source_passage: zero.public_id, parent: zero.public_id })
  const two = makePassage({ number: 2, source_kind: 'passage', source_passage: zero.public_id, parent: zero.public_id })
  const revived = makePassage({ number: 3, source_kind: 'vial', parent: one.public_id, source_vial_label: 'MYC 42 / 1 / 4' })

  it('hangs each passage under its parent, in the order of the list', () => {
    expect(shape(passageTree([zero, one, two, revived]))).toEqual([[0, [[1, [[3, []]]], [2, []]]]])
  })

  it('keeps a passage whose parent is not in the list as a root of its own, dropping none', () => {
    expect(shape(passageTree([one, revived]))).toEqual([[1, [[3, []]]]])
    expect(shape(passageTree([revived]))).toEqual([[3, []]])
    expect(shape(passageTree([]))).toEqual([])
  })

  it('says where each passage came from', () => {
    const all = [zero, one, two, revived]
    expect(all.map((p) => sourceLabel(p, all))).toEqual(['As received', 'Subculture of passage 0', 'Subculture of passage 0', 'Revived from vial MYC 42 / 1 / 4'])
  })
})
