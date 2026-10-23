import { type Browser, expect, type Locator, type Page, type TestInfo } from '@playwright/test'
import { signedInAs } from '../support.js'

/**
 * Role walkthroughs (#68): one test per task a person in a lab role really does, performed the
 * way that person would (visible links, labels, the keyboard where it is natural, no URL jumps)
 * and measured. Each task starts on Home, signed in, and ends when the person has the answer or
 * the result on screen, or gives up because the app has no way to do it.
 *
 * What is counted, only between start() and done():
 * - clicks, key presses, text entries (one per field typed into) and screens scrolled to reach
 *   a control (Playwright scrolls by itself, a person does not). Steps are their sum.
 * - page loads: changes of the path in the main frame (route changes of the SPA and reloads).
 *   A change of the query string alone (a filter) is no page load.
 * - API requests (`/api/` in the path), whoever started them.
 * - distinct screens, by route pattern.
 * - the run time, and an estimate of a person's time: the run time plus the keystroke-level
 *   model operators for each action (Card, Moran and Newell, "The keystroke-level model for user
 *   performance time with interactive systems", CACM 23(7), 1980). Scrolling is no operator
 *   there: one second per screen is our assumption.
 *
 * Data accumulates across runs on a local stack: every row a task needs is made in its setup,
 * before start(), through the API with a name unique to the run.
 */

export const RUN = Date.now().toString(36)

export type Role = 'curator' | 'technician' | 'manager' | 'viewer'

export interface WalkRecord {
  id: string
  role: Role
  task: string
  possible: boolean
  steps: number
  clicks: number
  keys: number
  entries: number
  chars: number
  scrolls: number
  looks: number
  pageLoads: number
  requests: number
  screens: string[]
  runSeconds: number
  personSeconds: number
  friction: string[]
  issues: string[]
}

/** Keystroke-level model operators, seconds. */
const KLM = {
  mental: 1.35, // M: decide or find the next thing
  point: 1.1, // P: move the pointer to a target
  button: 0.2, // BB: press and release a mouse button
  key: 0.28, // K: one key, an average typist
  home: 0.4, // H: hand between mouse and keyboard
  scroll: 1.0, // one screen of scrolling with a glance at it (an assumption, see above)
}

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g
const screenOf = (path: string) => path.replace(UUID, ':id')

export const DEV_USERS = ['bac-curator', 'bac-technician', 'bac-manager', 'bac-viewer', 'reg-manager'] as const
export type DevUser = (typeof DEV_USERS)[number]

export class Walk {
  private counting = false
  private started = 0
  private lastPath = ''
  private klm = 0
  private readonly counts = { clicks: 0, keys: 0, entries: 0, chars: 0, scrolls: 0, looks: 0, pageLoads: 0, requests: 0 }
  private readonly screens = new Set<string>()
  private readonly friction: string[] = []
  private readonly issues = new Set<string>()
  private possible = true

  readonly page: Page
  private readonly info: TestInfo
  private readonly meta: { id: string; role: Role; task: string }
  private readonly closeContext: () => Promise<void>

  private constructor(page: Page, info: TestInfo, meta: { id: string; role: Role; task: string }, closeContext: () => Promise<void>) {
    this.page = page
    this.info = info
    this.meta = meta
    this.closeContext = closeContext
    page.on('request', (request) => {
      if (this.counting && new URL(request.url()).pathname.startsWith('/api/')) this.counts.requests++
    })
    page.on('framenavigated', (frame) => {
      if (frame !== page.mainFrame()) return
      const path = new URL(frame.url()).pathname
      if (this.counting && path !== this.lastPath) {
        this.counts.pageLoads++
        this.screens.add(screenOf(path))
      }
      this.lastPath = path
    })
  }

  /** A fresh browser context with the user's shared session (walk.setup.ts signed it in). */
  static async as(browser: Browser, info: TestInfo, user: DevUser, meta: { id: string; role: Role; task: string }) {
    const context = await browser.newContext({ storageState: signedInAs(user), viewport: { width: 1280, height: 800 } })
    const page = await context.newPage()
    return new Walk(page, info, meta, () => context.close())
  }

  /** The person opens the app: Home, signed in. Counting starts here. */
  async start() {
    await this.page.goto('/')
    await expect(this.page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
    this.lastPath = '/'
    this.screens.add('/')
    this.counting = true
    this.started = performance.now()
  }

  /** Screens a person scrolls to bring the target into view (Playwright would do it unseen). */
  private async scrollTo(target: Locator) {
    await target.waitFor()
    const box = await target.boundingBox()
    const height = this.page.viewportSize()?.height ?? 800
    if (box === null) return
    const below = box.y + box.height - height
    const above = -box.y
    const distance = below > 0 ? below : above > 0 ? above : 0
    if (distance === 0) return
    const screens = Math.ceil(distance / height)
    this.counts.scrolls += screens
    this.klm += screens * KLM.scroll
    await target.scrollIntoViewIfNeeded()
  }

  async click(target: Locator) {
    await this.scrollTo(target)
    await target.click()
    this.counts.clicks++
    this.klm += KLM.mental + KLM.point + KLM.button
  }

  /** A native select: open it and pick the option, two clicks. */
  async choose(select: Locator, label: string | RegExp) {
    await this.scrollTo(select)
    const option = await select.locator('option').filter({ hasText: label }).first().getAttribute('value')
    await select.selectOption(option ?? '')
    this.counts.clicks += 2
    this.klm += KLM.mental + 2 * (KLM.point + KLM.button)
  }

  /** Click into a field and type, as a person does when the field is not next in tab order. */
  async type(field: Locator, text: string) {
    await this.click(field)
    await field.pressSequentially(text)
    this.counts.entries++
    this.counts.chars += text.length
    this.klm += KLM.home + text.length * KLM.key
  }

  /** Type into the focused control (after a Tab, or a field that took focus by itself). */
  async keys(text: string) {
    await this.page.keyboard.type(text)
    this.counts.entries++
    this.counts.chars += text.length
    this.klm += KLM.mental + text.length * KLM.key
  }

  async press(key: string, times = 1) {
    for (let i = 0; i < times; i++) await this.page.keyboard.press(key)
    this.counts.keys += times
    this.klm += times * KLM.key + (key === 'Enter' ? KLM.mental : 0)
  }

  /** The person scrolls to a part of the page and reads it. */
  async read(target: Locator) {
    await this.scrollTo(target)
    this.look()
  }

  /** How many screens tall the page is, and on which screen the target sits (1 = no scrolling). Not timed. */
  async screensOf(target: Locator) {
    const paused = performance.now()
    await target.waitFor()
    await this.page.waitForLoadState('networkidle')
    const height = this.page.viewportSize()?.height ?? 800
    const total = await this.page.evaluate(() => document.documentElement.scrollHeight)
    const top = await target.evaluate((element) => element.getBoundingClientRect().top + window.scrollY)
    this.started += performance.now() - paused
    return { total: Math.round((total / height) * 10) / 10, at: Math.floor(top / height) + 1 }
  }

  /** The person reads the screen to find something (a row, a value, a heading). */
  look(times = 1) {
    this.counts.looks += times
    this.klm += times * KLM.mental
  }

  /** Friction the task met, worst first, with an issue number when one covers it. */
  note(text: string, issue?: string) {
    this.friction.push(text)
    if (issue !== undefined) this.issues.add(issue)
  }

  /** The task cannot be done in the app today: the person stops here. */
  impossible(text: string, issue?: string) {
    this.possible = false
    this.friction.unshift(text)
    if (issue !== undefined) this.issues.add(issue)
  }

  /** A full-page screenshot of a friction point, kept with the run's results. Not timed. */
  async shot(name: string) {
    const paused = performance.now()
    const path = this.info.outputPath(`${this.meta.id}-${name}.png`)
    await this.page.waitForLoadState('networkidle')
    await expect(this.page.getByText(/^Loading/)).toHaveCount(0)
    await this.page.screenshot({ path, fullPage: true })
    await this.info.attach(`${this.meta.id}-${name}`, { path, contentType: 'image/png' })
    this.started += performance.now() - paused
  }

  /** Stops counting, attaches the record for the reporter and closes the context. */
  async done() {
    const runSeconds = (performance.now() - this.started) / 1000
    this.counting = false
    const { clicks, keys, entries, scrolls } = this.counts
    const record: WalkRecord = {
      ...this.meta,
      possible: this.possible,
      steps: clicks + keys + entries + scrolls,
      ...this.counts,
      screens: [...this.screens],
      runSeconds: Math.round(runSeconds * 10) / 10,
      personSeconds: Math.round(runSeconds + this.klm),
      friction: this.friction,
      issues: [...this.issues],
    }
    await this.info.attach('walkthrough', { body: JSON.stringify(record), contentType: 'application/json' })
    await this.closeContext()
    return record
  }
}

// Setup through the API, before start(): not counted.

type Row = Record<string, unknown>
const isRow = (value: unknown): value is Row => typeof value === 'object' && value !== null && !Array.isArray(value)
export const rows = (json: unknown): Row[] => {
  const list: unknown = isRow(json) ? json.results : json
  return Array.isArray(list) ? list.filter(isRow) : []
}
export const field = (row: unknown, key: string) => {
  const value: unknown = isRow(row) ? row[key] : undefined
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

/** A page signed in as the user, for setup only. */
export async function setupAs(browser: Browser, user: DevUser) {
  const context = await browser.newContext({ storageState: signedInAs(user) })
  const page = await context.newPage()
  await page.goto('/')
  return { page, close: () => context.close() }
}

/** A request with the page's session and CSRF token. A path without a leading slash is in the lab. */
export async function api(page: Page, lab: string, path: string, body?: Row, method = body === undefined ? 'GET' : 'POST') {
  const answer = await page.evaluate(
    async ([labPublicId, url, payload, verb]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
      const target = url.startsWith('/') ? url : `/api/v1/labs/${labPublicId}/${url}`
      const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) }
      const init: RequestInit = { method: verb, headers }
      if (payload !== undefined) init.body = JSON.stringify(payload)
      const response = await fetch(target, init)
      return { status: response.status, text: await response.text() }
    },
    [lab, path, body, method] as const,
  )
  const json: unknown = answer.text === '' ? null : JSON.parse(answer.text)
  if (answer.status >= 400) throw new Error(`${method} ${path}: ${answer.status} ${answer.text}`)
  return json
}

export async function labId(page: Page, name: string) {
  const lab = rows(await api(page, '', '/api/v1/labs/?limit=200')).find((row) => row.name === name)
  expect(lab, `lab ${name}`).toBeDefined()
  return field(lab, 'public_id')
}

const today = () => new Date().toLocaleDateString('sv')
const USES = ['research_noncommercial', 'research_commercial', 'teaching', 'diagnostics', 'production', 'reference_qc', 'patent_deposit_related', 'redistribution']

/** A deposit as received, with terms that leave commercial research on request. */
export async function receivedDeposit(page: Page, lab: string, name: string) {
  const depositor = rows(await api(page, lab, 'depositors/?search=Vzor'))[0]
  const terms = { mta: null, abs_scope: 'not_in_scope', country_of_origin: 'CZ', uses: USES.map((use) => ({ use, decision: use === 'research_commercial' ? 'on_request' : 'permit' })) }
  const body = { depositor: field(depositor, 'public_id'), received_on: today(), condition: 'intact', name_as_received: name, terms }
  return field(await api(page, lab, 'deposits/', body), 'public_id')
}

/** A strain through intake (received, checked, accepted) with its passage 0. */
export async function acceptedStrain(page: Page, lab: string, name: string, taxon: string) {
  const deposit = await receivedDeposit(page, lab, name)
  await api(page, lab, `deposits/${deposit}/start-check/`, {})
  const taxa = rows(await api(page, lab, `/api/v1/taxa/?search=${encodeURIComponent(taxon)}`))
  const accepted = { taxon: field(taxa.find((t) => t.name === taxon), 'public_id'), identified_on: today(), identification_method: '16S rRNA gene sequence', risk_group: 1, country_of_origin: 'CZ', restrictions: [] }
  await api(page, lab, `deposits/${deposit}/accept/`, accepted)
  const strain = rows(await api(page, lab, `strains/?search=${encodeURIComponent(name)}`))[0]
  const passage = rows(await api(page, lab, `passages/?strain=${field(strain, 'public_id')}`)).find((p) => p.number === 0)
  return { id: field(strain, 'public_id'), number: field(strain, 'accession_number'), passage: field(passage, 'public_id'), deposit }
}

/** A freezer of its own with a rack and the named 9 x 9 boxes in it. */
export async function freezerWithBoxes(page: Page, lab: string, freezer: string, boxes: string[]) {
  const unit = field(await api(page, lab, 'storage-units/', { kind: 'freezer', name: freezer, temperature_c: -80, max_risk_group: 2 }), 'public_id')
  const rack = field(await api(page, lab, 'storage-units/', { kind: 'rack', name: 'Rack 1', parent: unit, slot: 1 }), 'public_id')
  const types = rows(await api(page, lab, '/api/v1/box-types/'))
  const nine = field(types.find((t) => t.name === '81-place cryobox (9 x 9)'), 'public_id')
  const ids: string[] = []
  for (const [i, name] of boxes.entries()) {
    ids.push(field(await api(page, lab, 'storage-units/', { kind: 'box', name, parent: rack, slot: i + 1, box_type: nine }), 'public_id'))
  }
  return { freezer: unit, rack, boxes: ids }
}

/** A batch of the passage, into the box when given. Answers its vials' labels in seq order. */
export async function batch(page: Page, lab: string, passage: string, options: { count: number; method?: string; box?: string }) {
  const body: Row = { passage, method: options.method ?? 'cryo_minus80', purpose: 'distribution', cryoprotectant: '10 % glycerol', preserved_on: today(), vial_count: options.count }
  if (options.box !== undefined) body.box = options.box
  const created = field(await api(page, lab, 'batches/', body), 'public_id')
  const vials = rows(await api(page, lab, `vials/?batch=${created}&limit=200`))
  return vials.toSorted((a, b) => Number(a.seq) - Number(b.seq)).map((v) => field(v, 'label'))
}

/** A batch of distribution stock of the passage, not placed: its id and its vials in seq order. */
export async function batchOf(page: Page, lab: string, passage: string, count: number) {
  const body: Row = { passage, method: 'cryo_minus80', purpose: 'distribution', cryoprotectant: '10 % glycerol', preserved_on: today(), vial_count: count }
  const id = field(await api(page, lab, 'batches/', body), 'public_id')
  const vials = rows(await api(page, lab, `vials/?batch=${id}&limit=200`)).toSorted((a, b) => Number(a.seq) - Number(b.seq))
  return { id, vials: vials.map((v) => ({ id: field(v, 'public_id'), label: field(v, 'label') })) }
}

/** A passed identity, purity and viability check of the batch, recorded by the page's user (#17). */
export async function passAll(page: Page, lab: string, batchId: string, vial: string) {
  const methods = { identity: 'sequencing', purity: 'streak_plate', viability: 'growth' }
  for (const [kind, method] of Object.entries(methods)) {
    await api(page, lab, 'batch-checks/', { batch: batchId, kind, stage: 'after_preservation', checked_on: today(), method, result: 'pass', vial })
  }
}

/** From Home to a lab's page, the way every task starts: the lab picker's All labs, then the lab. */
export async function openLab(w: Walk, lab: string) {
  await w.click(w.page.getByRole('button', { name: /^(Lab|Select a lab)/ }))
  await w.click(w.page.getByRole('menuitem', { name: 'All labs' }))
  w.look()
  await w.click(w.page.getByRole('table', { name: 'Your labs' }).getByRole('link', { name: lab }))
  await expect(w.page.getByRole('heading', { level: 1, name: lab })).toBeVisible()
}

/** From the lab's page to a strain, by the strain list's search and the row it finds. */
export async function openStrain(w: Walk, search: string, row: RegExp) {
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains' }))
  await w.type(w.page.getByRole('searchbox', { name: 'Number or name' }), search)
  await w.press('Enter')
  const found = w.page.getByRole('table', { name: 'Strains' }).getByRole('row', { name: row })
  await expect(found).toHaveCount(1)
  w.look()
  await w.click(found.getByRole('link').first())
  await expect(w.page.getByRole('heading', { level: 2, name: 'Vials' })).toBeVisible()
}

/** A unit in the storage tree by the names along its path, from the top. */
function unitAt(w: Walk, path: RegExp[]) {
  let item = w.page.getByRole('tree')
  for (const name of path) item = item.getByRole('treeitem', { name })
  return item
}

/** Opens a unit's branch in the storage tree by a click on its arrow. */
export async function expandUnit(w: Walk, path: RegExp[]) {
  const item = unitAt(w, path)
  w.look()
  await w.click(item.locator(':scope > div [data-toggle]'))
  await expect(item).toHaveAttribute('aria-expanded', 'true')
}

/** A unit in the storage tree, opened by a click on its name. */
export async function openUnit(w: Walk, path: RegExp[]) {
  w.look()
  await w.click(unitAt(w, path).locator(':scope > div'))
}

// Distribution (#18): strains that may go out, and requests made through the API.

/**
 * A strain through intake whose terms name MTA STD version 2 (every use permitted), with a
 * released batch of distribution stock of `count` vials: one of them is used up by the checks.
 */
export async function supplyStrain(page: Page, lab: string, name: string, taxon: string, restrictions: Row[] = [], count = 4) {
  const depositor = rows(await api(page, lab, 'depositors/?search=Vzor'))[0]
  const mta = rows(await api(page, lab, 'mta-templates/')).find((t) => t.code === 'STD' && t.version === 2)
  const terms = { mta: field(mta, 'public_id'), abs_scope: 'not_in_scope', country_of_origin: 'CZ', uses: USES.map((use) => ({ use, decision: 'permit' })) }
  const deposit = field(await api(page, lab, 'deposits/', { depositor: field(depositor, 'public_id'), received_on: today(), condition: 'intact', name_as_received: name, terms }), 'public_id')
  await api(page, lab, `deposits/${deposit}/start-check/`, {})
  const taxa = rows(await api(page, lab, `/api/v1/taxa/?search=${encodeURIComponent(taxon)}`))
  const facts = { taxon: field(taxa.find((t) => t.name === taxon), 'public_id'), identified_on: today(), identification_method: '16S rRNA gene sequence', risk_group: 1, country_of_origin: 'CZ', restrictions }
  await api(page, lab, `deposits/${deposit}/accept/`, facts)
  const strain = rows(await api(page, lab, `strains/?search=${encodeURIComponent(name)}`))[0]
  const passage = rows(await api(page, lab, `passages/?strain=${field(strain, 'public_id')}`)).find((p) => p.number === 0)
  return { id: field(strain, 'public_id'), number: field(strain, 'accession_number'), passage: field(passage, 'public_id'), count }
}

/** Releases a checked batch: the curator's step after passAll. */
export async function release(page: Page, lab: string, batchId: string) {
  await api(page, lab, `batches/${batchId}/release/`, { reason: 'Identity, purity and viability passed.' })
}

/** A request of the seeded requester for the strain, with an accepted MTA (signed copy uploaded). */
export async function requestFor(page: Page, lab: string, strain: string, quantity: number, endUse: string) {
  const requester = rows(await api(page, lab, 'requesters/?search=Example%20Institute'))[0]
  const made = await api(page, lab, 'requests/', { requester: field(requester, 'public_id'), use: 'research_noncommercial', end_use: endUse, containment_level: 2, lines: [{ strain, quantity }] })
  const id = field(made, 'public_id')
  const mta = rows(await api(page, lab, 'mta-templates/')).find((t) => t.code === 'STD' && t.version === 2)
  const status = await page.evaluate(
    async ([url, mtaId]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
      const data = new FormData()
      for (const [k, v] of Object.entries({ mta: mtaId, signer_name: 'Walk Signatory', signer_role: 'head_of_institution', authorised_signatory: 'true', accepted_on: new Date().toLocaleDateString('sv') })) data.append(k, v)
      data.append('file', new Blob(['%PDF-1.4\n% walkthrough\n'], { type: 'application/pdf' }), 'signed.pdf')
      const response = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': decodeURIComponent(token) }, body: data })
      return response.status
    },
    [`/api/v1/labs/${lab}/requests/${id}/acceptances/`, field(mta, 'public_id')] as const,
  )
  expect(status).toBe(201)
  return { id, number: field(made, 'number') }
}
