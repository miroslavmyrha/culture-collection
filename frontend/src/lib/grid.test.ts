import { describe, expect, it } from 'vitest'
import { clampPos, moveFocus, samePos } from './grid'

const box = { rows: 9, cols: 9 }
const middle = { row: 4, col: 4 }
const topLeft = { row: 0, col: 0 }
const bottomRight = { row: 8, col: 8 }

describe('moveFocus', () => {
  it.each([
    ['ArrowUp', { row: 3, col: 4 }],
    ['ArrowDown', { row: 5, col: 4 }],
    ['ArrowLeft', { row: 4, col: 3 }],
    ['ArrowRight', { row: 4, col: 5 }],
    ['Home', { row: 4, col: 0 }],
    ['End', { row: 4, col: 8 }],
    ['PageUp', { row: 0, col: 4 }],
    ['PageDown', { row: 8, col: 4 }],
  ])('%s from the middle', (key, expected) => {
    expect(moveFocus(middle, key, box)).toEqual(expected)
  })

  it('Ctrl+Home and Ctrl+End go to the corners, Cmd too (the caller passes either)', () => {
    expect(moveFocus(middle, 'Home', box, true)).toEqual(topLeft)
    expect(moveFocus(middle, 'End', box, true)).toEqual(bottomRight)
  })

  it.each([
    ['ArrowUp', topLeft],
    ['ArrowLeft', topLeft],
    ['PageUp', topLeft],
    ['Home', topLeft],
  ])('%s stops at the top left, it never wraps', (key, pos) => {
    expect(moveFocus(pos, key, box)).toEqual(pos)
  })

  it.each([
    ['ArrowDown', bottomRight],
    ['ArrowRight', bottomRight],
    ['PageDown', bottomRight],
    ['End', bottomRight],
  ])('%s stops at the bottom right, it never wraps', (key, pos) => {
    expect(moveFocus(pos, key, box)).toEqual(pos)
  })

  it('does not wrap from the end of a row to the next row, or from the last row to the first', () => {
    expect(moveFocus({ row: 2, col: 8 }, 'ArrowRight', box)).toEqual({ row: 2, col: 8 })
    expect(moveFocus({ row: 2, col: 0 }, 'ArrowLeft', box)).toEqual({ row: 2, col: 0 })
    expect(moveFocus({ row: 8, col: 3 }, 'ArrowDown', box)).toEqual({ row: 8, col: 3 })
    expect(moveFocus({ row: 0, col: 3 }, 'ArrowUp', box)).toEqual({ row: 0, col: 3 })
  })

  it('works on a box that is not square', () => {
    const wide = { rows: 2, cols: 12 }
    expect(moveFocus({ row: 0, col: 3 }, 'End', wide, true)).toEqual({ row: 1, col: 11 })
    expect(moveFocus({ row: 0, col: 3 }, 'PageDown', wide)).toEqual({ row: 1, col: 3 })
    expect(moveFocus({ row: 1, col: 11 }, 'ArrowRight', wide)).toEqual({ row: 1, col: 11 })
  })

  it('a box of one position keeps every key on it', () => {
    for (const key of ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown'])
      expect(moveFocus(topLeft, key, { rows: 1, cols: 1 })).toEqual(topLeft)
  })

  it.each(['Enter', ' ', 'Escape', 'Tab', 'a', 'F2'])('leaves %j to someone else', (key) => {
    expect(moveFocus(middle, key, box)).toBeNull()
  })
})

describe('clampPos and samePos', () => {
  it('a position outside a smaller box moves to the nearest one inside', () => {
    expect(clampPos({ row: 9, col: 9 }, box)).toEqual(bottomRight)
    expect(clampPos({ row: 3, col: 2 }, box)).toEqual({ row: 3, col: 2 })
  })

  it('compares by row and column, and nothing equals nothing', () => {
    expect(samePos({ row: 1, col: 2 }, { row: 1, col: 2 })).toBe(true)
    expect(samePos({ row: 1, col: 2 }, { row: 2, col: 1 })).toBe(false)
    expect(samePos(null, null)).toBe(false)
  })
})
