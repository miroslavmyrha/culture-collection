import { sanitizeHtml } from '@/lib/sanitize'

type Props = { html: string; className?: string }

/** The only place allowed to render HTML. Allowlist sanitising in lib/sanitize.ts. */
export function SafeHtml({ html, className }: Props) {
  return <div className={className} dangerouslySetInnerHTML={{ __html: sanitizeHtml(html) }} />
}
