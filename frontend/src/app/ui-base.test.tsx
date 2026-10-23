import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Mono, StatusChip } from '@/components/ui'
import { renderWithProviders } from '@/test/render'

// The two shared pieces of the visual base, in the real theme.
const wrap = (ui: React.ReactElement) => renderWithProviders(ui)

describe('Mono', () => {
  it('shows its text unchanged, in the monospace stack', async () => {
    await wrap(
      <p>
        Strain <Mono>BAC 29 / 2 / 1</Mono>
      </p>,
    )
    const label = screen.getByText('BAC 29 / 2 / 1')
    expect(label.textContent).toBe('BAC 29 / 2 / 1')
    expect(getComputedStyle(label).fontFamily).toMatch(/monospace/)
    // A long hash breaks instead of widening the page.
    expect(getComputedStyle(label).overflowWrap).toBe('anywhere')
  })

  it('is the same style for every use', async () => {
    await wrap(
      <>
        <Mono>BAC 1</Mono>
        <Mono>2026/7</Mono>
      </>,
    )
    expect(getComputedStyle(screen.getByText('BAC 1')).fontFamily).toBe(getComputedStyle(screen.getByText('2026/7')).fontFamily)
  })
})

describe('StatusChip', () => {
  it('says the status in words and takes its colours from the tone', async () => {
    await wrap(
      <>
        <StatusChip tone="success">Released</StatusChip>
        <StatusChip tone="danger">Rejected</StatusChip>
      </>,
    )
    const released = getComputedStyle(screen.getByText('Released'))
    const rejected = getComputedStyle(screen.getByText('Rejected'))
    expect(released.backgroundColor).not.toBe(rejected.backgroundColor)
    expect(released.color).not.toBe(rejected.color)
  })
})
