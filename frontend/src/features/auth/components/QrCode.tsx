import { encode } from 'uqr'

/** One path for the dark modules: one square ("h1v1h-1z") per module, row by row. */
export function qrPath(data: boolean[][]): string {
  return data.flatMap((row, y) => row.flatMap((dark, x) => (dark ? [`M${x} ${y}h1v1h-1z`] : []))).join('')
}

/**
 * A QR code drawn as SVG elements from the encoded matrix (uqr): no image service sees the
 * secret, and no HTML string reaches the page (the CSP allows no Trusted Types policy, #238).
 */
export function QrCode({ value, label, size = 192 }: { value: string; label: string; size?: number }) {
  const { data, size: modules } = encode(value, { ecc: 'M', border: 2 })
  return (
    // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- an inline SVG drawn here has no <img> equivalent without a data URL; role="img" with a name is the pattern for it
    <svg role="img" aria-label={label} viewBox={`0 0 ${modules} ${modules}`} width={size} height={size} shapeRendering="crispEdges">
      <rect width={modules} height={modules} fill="#fff" />
      <path d={qrPath(data)} fill="#000" />
    </svg>
  )
}
