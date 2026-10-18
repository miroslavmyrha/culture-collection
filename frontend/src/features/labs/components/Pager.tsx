import { Box, Button, Typography } from '@/components/ui'
import { useFocusReturnOnUnmount } from '@/lib/focus'

type Props = {
  label: string
  count: number
  shown: number
  limit: number
  offset: number
  loading: boolean
  onOffsetChange: (offset: number) => void
}

// Looks disabled without being disabled: a disabled button drops the focus to the body.
const looksDisabled = { '&[aria-disabled="true"]': { color: 'text.disabled', cursor: 'default' } }

/**
 * Previous and next for a limit/offset list. The page owns the URL, this only asks for an offset.
 * aria-disabled and a guard, never `disabled`: Next disables itself while the next page loads
 * and again on the last page, and disabling the focused button drops focus to the body.
 */
export function Pager({ label, count, shown, limit, offset, loading, onOffsetChange }: Props) {
  if (count <= limit && offset === 0) return null
  const noPrevious = offset === 0 || loading
  const noNext = offset + limit >= count || loading
  return (
    <Box component="nav" aria-label={label} sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 2, mt: 2 }}>
      <Typography>
        {offset + 1} to {offset + shown} of {count}
      </Typography>
      <Button
        aria-disabled={noPrevious}
        sx={looksDisabled}
        onClick={() => {
          if (!noPrevious) onOffsetChange(Math.max(0, offset - limit))
        }}
      >
        Previous
      </Button>
      <Button
        aria-disabled={noNext}
        sx={looksDisabled}
        onClick={() => {
          if (!noNext) onOffsetChange(offset + limit)
        }}
      >
        Next
      </Button>
    </Box>
  )
}

/** A page past the end (a shared link after rows were removed): offer the first page. */
export function PastTheEnd({ onFirstPage }: { onFirstPage: () => void }) {
  // The button goes away with the empty page: focus moves to the section's heading.
  const remember = useFocusReturnOnUnmount()
  return (
    <Typography>
      This page is empty.{' '}
      <Button
        onClick={(event) => {
          remember(event.currentTarget)
          onFirstPage()
        }}
      >
        Go to the first page
      </Button>
    </Typography>
  )
}
