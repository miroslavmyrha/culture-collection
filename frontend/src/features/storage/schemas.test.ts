import { describe, expect, it } from 'vitest'
import { makeUnitRow } from '@/test/factories'
import { canManageStorage, createBody, createUnitSchema, emptyFields, fieldsBody, HOLDS, positionLabel, sizeLabel, unitSummary } from './schemas'

describe('box coordinates (ADR 0008, D6)', () => {
  it('labels rows with letters and columns with numbers, both from 1', () => {
    expect(positionLabel(1, 1)).toBe('A1')
    expect(positionLabel(9, 9)).toBe('I9')
    expect(positionLabel(8, 12)).toBe('H12')
    expect(positionLabel(26, 26)).toBe('Z26')
    expect(sizeLabel(10, 10)).toBe('10 x 10, A1 to J10')
  })
})

describe('unitSummary', () => {
  it.each([
    [{ kind: 'freezer' as const, temperature_c: -80 }, 'freezer, -80\u00a0°C'],
    [{ kind: 'rack' as const, slot: 3, max_risk_group: null }, 'rack in slot 3'],
    [{ kind: 'box' as const, slot: 1, rows: 9, cols: 9 }, 'box in slot 1, 9 x 9'],
    [{ kind: 'ln2_tank' as const, status: 'out_of_service' as const }, 'LN2 tank, out of service'],
    [{ kind: 'box' as const, rows: 5, cols: 5, status: 'retired' as const }, 'box, 5 x 5, retired'],
  ])('describes %j as "%s"', (overrides, text) => {
    expect(unitSummary(makeUnitRow(overrides))).toBe(text)
  })
})

describe('who builds storage', () => {
  it.each([
    ['viewer', false],
    ['technician', false],
    ['curator', true],
    ['manager', true],
    [undefined, false],
  ] as const)('%s: %s', (role, may) => {
    expect(canManageStorage(role)).toBe(may)
  })

  it('mirrors the kind spec of the server', () => {
    expect(HOLDS).toEqual({ freezer: ['rack', 'box'], ln2_tank: ['rack', 'box'], rack: ['box'], box: [] })
  })
})

const issues = (value: object) => createUnitSchema.safeParse(value).error?.issues.map((i) => [i.path.join('.'), i.message]) ?? []

describe('the unit form', () => {
  const valid = { kind: 'freezer' as const, slot: '', ...emptyFields(), name: 'Freezer A', max_risk_group: '2' as const }

  it('accepts a freezer with its cap', () => {
    expect(issues(valid)).toEqual([])
  })

  it.each([
    [{ name: '  ' }, 'name', 'Enter a name'],
    [{ max_risk_group: '' }, 'max_risk_group', 'A freezer or tank states the highest risk group it may hold'],
    [{ temperature_c: '-274' }, 'temperature_c', 'Enter whole degrees from -273 to 100'],
    [{ temperature_c: '-80.5' }, 'temperature_c', 'Enter whole degrees from -273 to 100'],
    [{ barcode: 'A B' }, 'barcode', 'A barcode has no spaces'],
    [{ kind: 'box', box_type: '' }, 'box_type', 'Choose the box type'],
    [{ kind: 'rack', slot: '0' }, 'slot', 'Enter a slot number from 1'],
  ])('refuses %j on %s', (change, path, message) => {
    expect(issues({ ...valid, ...change })).toContainEqual([path, message])
  })

  it('sends numbers as numbers, empty as null, and a box type only for a box', () => {
    expect(createBody({ ...valid, temperature_c: ' -80 ', barcode: ' FRZ-1 ', box_type: 'x' }, null)).toEqual({
      kind: 'freezer',
      parent: null,
      slot: null,
      name: 'Freezer A',
      barcode: 'FRZ-1',
      temperature_c: -80,
      max_risk_group: 2,
      box_type: null,
    })
    expect(createBody({ ...valid, kind: 'box', slot: '4', max_risk_group: '', box_type: 'bt' }, 'rack')).toMatchObject({ parent: 'rack', slot: 4, max_risk_group: null, box_type: 'bt' })
    expect(fieldsBody('rack', { ...emptyFields(), name: 'R' })).toEqual({ name: 'R', barcode: '', temperature_c: null, max_risk_group: null, box_type: null })
  })

  it('fills the edit form from a unit', () => {
    const box = makeUnitRow({ kind: 'box', name: 'Box 1', barcode: 'BX-1', max_risk_group: 1, box_type: { public_id: 'bt', name: 'Cryobox', rows: 9, cols: 9 } })
    expect(emptyFields(box)).toEqual({ name: 'Box 1', barcode: 'BX-1', temperature_c: '', max_risk_group: '1', box_type: 'bt' })
  })
})
