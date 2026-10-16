import { describe, expect, it } from 'vitest'
import { reported } from '@/test/reports'
import { onUnhandledRejection, reportError } from './report'

const rejection = (reason: unknown) => Object.assign(new Event('unhandledrejection'), { reason, promise: Promise.resolve() })

describe('report', () => {
  it('sends unhandled rejections to the sink', () => {
    const error = new Error('boom')
    onUnhandledRejection(rejection(error))
    expect(reported).toEqual([{ error, context: { source: 'unhandledrejection' } }])
  })

  it('ignores aborts', () => {
    onUnhandledRejection(rejection(new DOMException('aborted', 'AbortError')))
    reportError(new DOMException('aborted', 'AbortError'))
    expect(reported).toEqual([])
  })
})
