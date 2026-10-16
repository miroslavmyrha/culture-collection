import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ALLOWED_ATTR } from '@/lib/sanitize'
import { SafeHtml } from './SafeHtml'

const html = (input: string) => render(<SafeHtml html={input} />).container.innerHTML

describe('SafeHtml', () => {
  it('keeps allowed formatting and safe links', () => {
    expect(html('<p><strong>Hi</strong> <a href="https://example.org/a b" title="t">x</a></p>')).toBe(
      '<div><p><strong>Hi</strong> <a href="https://example.org/a b" title="t">x</a></p></div>',
    )
  })

  it.each([
    ['img with onerror', '<img src=x onerror=alert(1)>ok', '<div>ok</div>'],
    ['remote image', '<p><img src="https://tracker.example/p.gif">text</p>', '<div><p>text</p></div>'],
    ['script', '<script>alert(1)</script>ok', '<div>ok</div>'],
    ['javascript link', '<a href="javascript:alert(1)">x</a>', '<div><a>x</a></div>'],
    ['data link', '<a href="data:text/html,x">x</a>', '<div><a>x</a></div>'],
    ['style attribute', '<p style="position:fixed">x</p>', '<div><p>x</p></div>'],
    ['iframe', '<iframe src="https://example.org"></iframe>ok', '<div>ok</div>'],
    ['form', '<form action="/x"><input name="a"></form>ok', '<div>ok</div>'],
    ['target blank', '<a href="https://example.org" target="_blank">x</a>', '<div><a href="https://example.org">x</a></div>'],
    ['event handler whose value looks like a path', '<a href="/a" onclick="/x/;alert(1)">x</a>', '<div><a href="/a">x</a></div>'],
  ])('strips %s', (_name, input, expected) => {
    expect(html(input)).toBe(expected)
  })

})

// Invariant: every allowed attribute survives with a realistic value. DOMPurify checks allowed
// attributes it does not list as URI-safe against ALLOWED_URI_REGEXP, which once stripped
// numeric values such as colspan="2".
describe('SafeHtml allowed attributes (invariant)', () => {
  const samples: Record<string, string> = {
    href: '<a href="/samples?page=2#top">x</a>',
    title: '<p title="Freezer 3, shelf B">x</p>',
    colspan: '<table><tbody><tr><td colspan="2">x</td></tr></tbody></table>',
    rowspan: '<table><tbody><tr><td rowspan="3">x</td></tr></tbody></table>',
  }

  it('has a sample for every allowed attribute', () => {
    expect(Object.keys(samples).toSorted()).toEqual(ALLOWED_ATTR.toSorted())
  })

  it.each(Object.entries(samples))('keeps %s', (_attr, input) => {
    expect(html(input)).toBe(`<div>${input}</div>`)
  })
})
