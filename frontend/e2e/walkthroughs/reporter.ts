import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { FullConfig, Reporter, TestCase, TestResult } from '@playwright/test/reporter'
import type { Role, WalkRecord } from './walk.js'

const ROLES: Role[] = ['curator', 'technician', 'manager', 'viewer']

/** Collects each walkthrough's record and writes one table per role (summary.md, summary.json). */
export default class WalkthroughReporter implements Reporter {
  private readonly records: WalkRecord[] = []
  private outputDir = 'test-results/walkthroughs'

  onBegin(config: FullConfig) {
    this.outputDir = config.projects[0]?.outputDir ?? this.outputDir
  }

  onTestEnd(_test: TestCase, result: TestResult) {
    for (const attachment of result.attachments) {
      if (attachment.name !== 'walkthrough' || attachment.body === undefined) continue
      const record: WalkRecord = JSON.parse(attachment.body.toString('utf8'))
      this.records.push(record)
    }
  }

  onEnd() {
    if (this.records.length === 0) return
    const sorted = this.records.toSorted((a, b) => ROLES.indexOf(a.role) - ROLES.indexOf(b.role) || a.id.localeCompare(b.id, 'en', { numeric: true }))
    const lines: string[] = []
    for (const role of ROLES) {
      const mine = sorted.filter((r) => r.role === role)
      if (mine.length === 0) continue
      lines.push(`## ${role[0]?.toUpperCase()}${role.slice(1)}`, '')
      lines.push('| Task | Possible | Steps | Page loads | Requests | Time (run) | Time (person, est.) | Main friction |')
      lines.push('|---|---|---|---|---|---|---|---|')
      for (const r of mine) {
        const friction = r.friction[0] ?? ''
        lines.push(`| ${r.id} ${r.task} | ${r.possible ? 'yes' : 'no'} | ${r.steps} | ${r.pageLoads} | ${r.requests} | ${r.runSeconds} s | ${r.personSeconds} s | ${friction} |`)
      }
      lines.push('')
    }
    mkdirSync(this.outputDir, { recursive: true })
    writeFileSync(join(this.outputDir, 'summary.md'), lines.join('\n'))
    writeFileSync(join(this.outputDir, 'summary.json'), JSON.stringify(sorted, null, 2))
    process.stdout.write(`\n${lines.join('\n')}\nWritten to ${join(this.outputDir, 'summary.md')}\n`)
  }

  printsToStdio() {
    return false
  }
}
