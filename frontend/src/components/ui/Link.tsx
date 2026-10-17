import MuiLink, { type LinkProps as MuiLinkProps } from '@mui/material/Link'
import { createLink } from '@tanstack/react-router'

function MuiAnchor(props: MuiLinkProps) {
  return <MuiLink {...props} />
}

/**
 * A router link with MUI styling and typed `to`/`params`/`search`. The router sets
 * aria-current="page" on the active link. External URLs go through safeHref, not here.
 */
export const Link = createLink(MuiAnchor)
