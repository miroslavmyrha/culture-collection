import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
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
  ])('strips %s', (_name, input, expected) => {
    expect(html(input)).toBe(expected)
  })
})
