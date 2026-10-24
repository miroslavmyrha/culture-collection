import { describe, expect, it } from 'vitest'
import { makeSearchGroup, makeSearchHit, SEARCH_LAB } from '@/test/factories'
import { entriesOf, exactHit } from './schemas'

const OTHER = '00000000-0000-4000-8000-0000000000c1'

describe('the entries of the search results', () => {
  it('ends a group with its list per lab only where the lab holds more than the group shows', () => {
    const hits = [makeSearchHit(), makeSearchHit({ lab: OTHER, lab_code: 'MYC' })]
    const group = makeSearchGroup({
      hits,
      total: 4,
      labs: [
        { lab: SEARCH_LAB, lab_code: 'BAC', total: 1 },
        { lab: OTHER, lab_code: 'MYC', total: 3 },
      ],
    })
    const [section] = entriesOf([group], 'Bacillus')
    expect(section?.entries.map((entry) => entry.name)).toEqual([expect.stringMatching(/^BAC \d+, BAC, Active\./), expect.stringMatching(/^BAC \d+, MYC, Active\./), 'All 3 strains in MYC'])
    const all = section?.entries[2]
    expect(all?.target).toEqual({ to: '/labs/$labId/strains', params: { labId: OTHER }, search: { search: 'Bacillus' } })
  })

  it('has no list entry when every match is shown, and none for vials', () => {
    const shown = makeSearchGroup({ hits: [makeSearchHit(), makeSearchHit()] })
    expect(entriesOf([shown], 'BAC')[0]?.entries.map((entry) => entry.type)).toEqual(['hit', 'hit'])
    const vials = makeSearchGroup({ kind: 'vial', total: 9, hits: [makeSearchHit({ strain: SEARCH_LAB })] })
    expect(entriesOf([vials], 'TUBE')[0]?.entries.map((entry) => entry.type)).toEqual(['hit'])
  })

  it('names the one exact hit across the groups, and none when there are two', () => {
    const one = makeSearchHit({ exact: true })
    expect(exactHit([makeSearchGroup({ hits: [one, makeSearchHit()] })])?.hit).toBe(one)
    expect(exactHit([makeSearchGroup({ hits: [one] }), makeSearchGroup({ kind: 'vial', hits: [makeSearchHit({ exact: true })] })])).toBeNull()
    expect(exactHit([])).toBeNull()
  })
})
