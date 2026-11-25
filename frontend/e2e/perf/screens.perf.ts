import { expect, type Locator, type Page, test } from '@playwright/test'
import { secondFactor } from '../support.js'

// Time from navigation to the screen's content on a seed_scale database (#71). The numbers go to
// the console as a Markdown table; nothing is asserted but that each screen shows its content.
const USER = process.env.PERF_USER ?? 'bac-manager'
const PASSWORD = process.env.DEV_PASSWORD ?? 'dev-password-long-enough'
const TOTP = process.env.DEV_TOTP_SECRET ?? 'JBSWY3DPEHPK3PXPDEVSEEDSECRET234'
const LAB = process.env.PERF_LAB ?? 'BAC'

async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await secondFactor(page, TOTP)
  await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
}

async function api<T>(page: Page, url: string): Promise<T> {
  const answer: T = await page.evaluate(async (where) => (await fetch(where)).json(), url)
  return answer
}

const firstRow = (p: Page) => p.getByRole('main').getByRole('row').nth(1)

async function timed(page: Page, path: string, content: (page: Page) => Locator): Promise<number> {
  const started = Date.now()
  await page.goto(path)
  await expect(content(page)).toBeVisible({ timeout: 60_000 })
  return Date.now() - started
}

test('time to content of the main screens', async ({ page }) => {
  await signIn(page)
  const labs = await api<{ results: { public_id: string; code: string }[] }>(page, '/api/v1/labs/?limit=200')
  const lab = labs.results.find((l) => l.code === LAB)?.public_id ?? ''
  const strains = await api<{ results: { public_id: string }[] }>(page, `/api/v1/labs/${lab}/strains/?limit=1&search=SCALE`)
  const strain = strains.results[0]?.public_id ?? ''
  const tree = await api<{ public_id: string; kind: string }[]>(page, `/api/v1/labs/${lab}/storage-units/`)
  const box = tree.find((u) => u.kind === 'box')?.public_id ?? ''
  const screens: [string, string, (p: Page) => Locator][] = [
    ['home', '/', (p) => p.getByRole('heading', { level: 1, name: 'Home' })],
    ['strain list', `/labs/${lab}/strains`, firstRow],
    ['deposit list', `/labs/${lab}/deposits`, firstRow],
    ['request list', `/labs/${lab}/requests`, (p) => p.getByRole('heading', { level: 1 })],
    ['storage tree', `/labs/${lab}/storage`, (p) => p.getByRole('treeitem').first()],
    ['box', `/labs/${lab}/storage/${box}`, (p) => p.getByRole('heading', { level: 1 })],
    ['strain page', `/labs/${lab}/strains/${strain}`, (p) => p.getByRole('heading', { level: 1 })],
    ['strain material', `/labs/${lab}/strains/${strain}/material`, firstRow],
  ]
  const lines = ['| screen | ms to content |', '|---|---:|']
  for (const [name, path, content] of screens) lines.push(`| ${name} | ${await timed(page, path, content)} |`)
  process.stdout.write(`${lines.join('\n')}\n`)
})
