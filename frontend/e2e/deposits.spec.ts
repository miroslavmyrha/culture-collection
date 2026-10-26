import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, watchCsp } from './support.js'

// Each test walks several pages and scans them with axe: real work, 5 to 25 s on a quiet machine and over
// the 30 s default on a busy one (#60).
test.describe.configure({ timeout: 120_000 })

// Deposit intake against the real API (seed_e2e: e2e-curator and e2e-viewer in "E2E lab", the
// depositor "E2E Depositor", MTA STD version 1, no permits). Each run adds deposits and strains:
// numbers are never reused and nothing is deleted, so the tests find theirs by a name made
// unique per run. B. subtilis is risk group 1 (LPSN, DSMZ); the permit gate is tried on the
// invented Testella exempli. It works as the sessions auth.setup.ts signed in.

const RUN = Date.now().toString(36)

async function as(browser: Browser, username: string, width = 1280) {
  const context = await browser.newContext({ storageState: signedInAs(username), viewport: { width, height: width === 320 ? 640 : 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

async function openLab(page: Page) {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
}

const fitsWidth = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth)

/** Every use permitted, by keyboard: a native select picks the option by its first letters. */
async function permitEveryUse(page: Page) {
  const uses = page.getByRole('group', { name: 'Uses' }).getByRole('combobox')
  await expect(uses.first()).toBeFocused()
  for (let i = 0; i < 8; i++) {
    await page.keyboard.type('Pe')
    await expect(uses.nth(i)).toHaveValue('permit')
    await page.keyboard.press('Tab')
  }
}

test('a curator receives, checks and accepts a deposit by keyboard, and finds the new strain', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator')
  const violations = await watchCsp(page)
  await openLab(page)
  await page.getByRole('link', { name: 'Strains' }).click()
  const receive = page.getByRole('link', { name: 'Receive a deposit' })
  await receive.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveTitle('Receive a deposit in E2E lab | Culture collection')
  const form = page.getByRole('form', { name: 'Receive a deposit' })

  // From here on only keys: Tab moves through the form in reading order.
  const depositor = form.getByRole('combobox', { name: 'Depositor' })
  await depositor.focus()
  await page.keyboard.type('E2E Dep')
  await expect(page.getByRole('option', { name: /E2E Depositor/ })).toBeVisible()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(depositor).toHaveValue('E2E Depositor, Example University')
  await page.keyboard.press('Tab')
  await expect(form.getByRole('button', { name: 'Add a depositor' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(form.getByRole('textbox', { name: 'Received on' })).toBeFocused()
  await page.keyboard.press('Tab')
  await page.keyboard.type(`B. subtilis e2e ${RUN}`)
  await page.keyboard.press('Tab')
  await expect(form.getByRole('combobox', { name: 'Condition on arrival' })).toHaveValue('intact')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(form.getByRole('textbox', { name: 'Passages stated by the depositor' })).toBeFocused()
  await page.keyboard.type('2')
  await page.keyboard.press('Tab')
  await permitEveryUse(page)
  const mta = form.getByRole('combobox', { name: 'MTA' })
  await expect(mta).toBeFocused()
  await page.keyboard.type('STD')
  await expect(mta).not.toHaveValue('')
  await page.keyboard.press('Tab')
  await page.keyboard.type('Not')
  await expect(form.getByRole('combobox', { name: 'ABS scope' })).toHaveValue('not_in_scope')
  await page.keyboard.press('Tab')
  await page.keyboard.type('Czechia')
  await expect(form.getByRole('combobox', { name: 'Country of origin' })).toHaveValue('CZ')
  await form.getByRole('button', { name: 'Record the deposit' }).focus()
  await page.keyboard.press('Enter')

  // The deposit's page: received, its terms as version 1, the check not started.
  await expect(page.getByRole('heading', { level: 1, name: `Deposit B. subtilis e2e ${RUN}` })).toBeVisible()
  await expect(page).toHaveTitle(`Deposit B. subtilis e2e ${RUN} | Culture collection`)
  await expect(page.getByRole('heading', { level: 2, name: 'Terms, version 1' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Uses' })).toContainText('Redistribution to third parties')
  const start = page.getByRole('button', { name: 'Start checking' })
  await start.focus()
  await page.keyboard.press('Enter')
  // The button goes with the step: focus lands on the section's heading, not on the body.
  await expect(page.getByRole('heading', { level: 2, name: 'Check and decision' })).toBeFocused()

  // Accept with what the check found, by keyboard.
  const accept = page.getByRole('form', { name: 'Accept the deposit' })
  await expect(accept.getByText(`B. subtilis e2e ${RUN}`)).toBeVisible()
  const taxon = accept.getByRole('combobox', { name: 'Taxon' })
  await taxon.focus()
  await page.keyboard.type('subt')
  await expect(page.getByRole('option', { name: /Bacillus subtilis/ })).toBeVisible()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Tab')
  await expect(accept.getByRole('textbox', { name: 'Identified on' })).toBeFocused()
  await page.keyboard.press('Tab')
  await page.keyboard.type('16S rRNA gene sequence')
  await page.keyboard.press('Tab')
  await page.keyboard.type('1')
  await expect(accept.getByRole('combobox', { name: 'Risk group' })).toHaveValue('1')
  await accept.getByRole('combobox', { name: 'Country of origin' }).focus()
  await expect(accept.getByRole('combobox', { name: 'Country of origin' })).toHaveValue('CZ') // from the terms
  await accept.getByRole('button', { name: 'Accept and add the strain' }).focus()
  await page.keyboard.press('Enter')

  const strainLink = page.getByRole('link', { name: /^E2E \d+$/ })
  await expect(strainLink).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Check and decision' })).toBeFocused()
  const number = (await strainLink.textContent()) ?? ''
  await strainLink.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: number })).toBeVisible()
  await expect(page.getByText(`B. subtilis e2e ${RUN}`)).toBeVisible()

  // In the strain list and the deposit list, found by the run's name.
  await page.goto(page.url().replace(/\/strains\/.*$/, `/strains?search=${RUN}`))
  await expect(page.getByRole('row', { name: new RegExp(RUN) }).getByRole('link', { name: number })).toBeVisible()
  await page.goto(page.url().replace(/\/strains\?.*$/, `/deposits?search=${RUN}&status=accepted`))
  await expect(page.getByRole('row', { name: new RegExp(RUN) })).toContainText(number)
  expect(violations()).toEqual([])
  await close()
})

async function receiveAndCheck(page: Page, name: string) {
  // The API through the page's own session: the screens are covered by the test above.
  const deposit = await page.evaluate(async (asReceived) => {
    await fetch('/api/v1/auth/csrf/')
    const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
    const lab = location.pathname.split('/')[2] ?? ''
    const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token }
    const depositors: { results: { public_id: string }[] } = await (await fetch(`/api/v1/labs/${lab}/depositors/?search=E2E`)).json()
    const uses = ['research_noncommercial', 'research_commercial', 'teaching', 'diagnostics', 'production', 'reference_qc', 'patent_deposit_related', 'redistribution']
    const body = {
      depositor: depositors.results[0]?.public_id,
      received_on: new Date().toLocaleDateString('sv'),
      condition: 'intact',
      name_as_received: asReceived,
      terms: { mta: null, abs_scope: 'unknown', uses: uses.map((use) => ({ use, decision: 'on_request' })) },
    }
    const created: { public_id: string } = await (await fetch(`/api/v1/labs/${lab}/deposits/`, { method: 'POST', headers, body: JSON.stringify(body) })).json()
    await fetch(`/api/v1/labs/${lab}/deposits/${created.public_id}/start-check/`, { method: 'POST', headers })
    return { lab, id: created.public_id }
  }, name)
  await page.goto(`/labs/${deposit.lab}/deposits/${deposit.id}`)
  await expect(page.getByRole('form', { name: 'Accept the deposit' })).toBeVisible()
}

test('a VRAT strain is refused at acceptance while the lab holds no SÚJB permit, and the deposit stays in its check', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator')
  await openLab(page)
  await receiveAndCheck(page, `Testella exempli refused ${RUN}`)
  const form = page.getByRole('form', { name: 'Accept the deposit' })
  await form.getByRole('combobox', { name: 'Taxon' }).fill('exempli')
  await page.getByRole('option', { name: /Testella exempli/ }).click()
  await form.getByRole('textbox', { name: 'Identification method' }).fill('MALDI-TOF MS')
  await form.getByRole('combobox', { name: 'Risk group' }).selectOption('2')
  await form.getByRole('button', { name: 'Add a restriction' }).click()
  const kind = form.getByRole('group', { name: 'Restriction 1' }).getByRole('combobox', { name: 'Kind' })
  await kind.selectOption('cz_vrat')
  await form.getByRole('group', { name: 'Restriction 1' }).getByRole('textbox', { name: 'List entry' }).fill('Příloha 1, bod 2')
  await form.getByRole('button', { name: 'Accept and add the strain' }).click()
  await expect(kind).toHaveAttribute('aria-invalid', 'true')
  await expect(kind).toHaveAccessibleDescription(/no valid SÚJB permit for highly risky agents \(VRAT\)/)
  await expect(kind).toBeFocused()
  await page.reload()
  await expect(page.getByText('Status: Checking.')).toBeVisible()
  await close()
})

test('a curator rejects a deposit with a reason: no strain, and the dialog passes axe', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator')
  await openLab(page)
  await receiveAndCheck(page, `Testella exempli rejected ${RUN}`)
  const reject = page.getByRole('button', { name: 'Reject the deposit' })
  await reject.click()
  const dialog = page.getByRole('alertdialog', { name: `Reject Testella exempli rejected ${RUN}?` })
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  expect(await axe(page, '[role="alertdialog"]')).toEqual([])
  await dialog.getByRole('textbox', { name: 'Reason' }).fill('Mixed culture on the purity plate.')
  await dialog.getByRole('button', { name: 'Reject the deposit' }).click()
  await expect(page.getByText(/^Rejected on .*: Mixed culture on the purity plate\.$/)).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Check and decision' })).toBeFocused()
  await close()
})

test('a viewer sees no deposit, in the screen and at the API', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-viewer')
  await openLab(page)
  await expect(page.getByRole('link', { name: 'Deposits' })).toHaveCount(0)
  await page.goto(`${page.url()}/deposits`)
  await expect(page.getByText('Only curators and managers see deposits')).toBeVisible()
  const status = await page.evaluate(async () => {
    const lab = location.pathname.split('/')[2] ?? ''
    return (await fetch(`/api/v1/labs/${lab}/deposits/`)).status
  })
  expect(status).toBe(403)
  await close()
})

test('the deposit pages fit 320 px without scrolling sideways and pass axe', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator', 320)
  const violations = await watchCsp(page)
  await openLab(page)
  await page.getByRole('link', { name: 'Deposits' }).click()
  await expect(page.getByRole('table', { name: 'Deposits' })).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  await page.getByRole('table', { name: 'Deposits' }).getByRole('link').first().click()
  await expect(page.getByRole('heading', { level: 2, name: 'Check and decision' })).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  await page.goBack()
  await page.getByRole('link', { name: 'Receive a deposit' }).click()
  await expect(page.getByRole('form', { name: 'Receive a deposit' })).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  for (const link of ['Depositors', 'MTA templates']) {
    await openLab(page)
    await page.getByRole('link', { name: link }).click()
    await expect(page.getByRole('heading', { level: 1, name: `${link} of E2E lab` })).toBeVisible()
    expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
    expect(await axe(page, 'body')).toEqual([])
  }
  expect(violations()).toEqual([])
  await close()
})
