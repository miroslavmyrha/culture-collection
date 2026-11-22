import { describe, expect, it } from 'vitest'
import { creationOptions, requestOptions } from './factors'

// The server's WebAuthn options are read without trusting them (#176).
describe('the key options', () => {
  const creation = { challenge: 'Y2hhbGxlbmdl', rp: { id: 'localhost', name: 'cultures' }, user: {}, pubKeyCredParams: [] }

  it('take creation options with a challenge and a relying party', () => {
    expect(creationOptions(creation)).toBe(creation)
  })

  it.each([null, 'options', {}, { challenge: 1 }, { challenge: 'Y2hhbGxlbmdl' }])('refuse creation options without both (%j)', (value) => {
    expect(() => creationOptions(value)).toThrow('The server sent no key options.')
  })

  it('take request options with a challenge', () => {
    const request = { challenge: 'Y2hhbGxlbmdl', allowCredentials: [] }
    expect(requestOptions(request)).toBe(request)
  })

  it.each([undefined, 7, { allowCredentials: [] }])('refuse request options without a challenge (%j)', (value) => {
    expect(() => requestOptions(value)).toThrow('The server sent no key options.')
  })
})
